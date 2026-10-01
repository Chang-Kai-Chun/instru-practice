"""
跟 jv_pv_sequence.py 做的是同一件事：
觸發 kitty 進行 JV 掃描，同時 6211 錄製 PV 訊號。

v2 修正：原本把「等 kitty」跟「讀 6211」合併放在同一個函式、依序執行，
結果 kitty 卡住時，連 6211 已經錄好、存在硬體緩衝區裡的資料都拿不到。
改回「kitty、6211 各自獨立完成、各自存檔」，kitty 卡住也不影響 PV 資料
正常存出來。

kitty 的「設定 + 觸發等待」已確認合併成同一執行緒也沒有改善卡住的狀況，
所以「不同執行緒操作同一個 GPIB 連線」這個假設目前看起來不是真正原因，
先保留合併寫法（沒有壞處），但不再依賴它解決卡住的問題。
"""

import time
import csv
import asyncio
import nidaqmx
from nidaqmx.constants import AcquisitionType, Edge, TerminalConfiguration
import pyvisa

from instru_package import reset_voltage, file_create, config

dev_name = config.device_name

SAMPLE_RATE = 1000.0
DURATION_SECONDS = 15  # 掃描 ~6 秒 + 標記脈衝 1.5 秒 + 餘裕
TOTAL_SAMPLES = int(SAMPLE_RATE * DURATION_SECONDS)

TRIGGER_LINE = "port1/line0"
TRIGGER_INPUT = f"/{dev_name}/PFI0"

KITTY_RESOURCE = "GPIB0::24::INSTR"
KITTY_TIMEOUT_MS = 90000


def _arm_kitty():
    """設定 kitty 為等待 SOT 觸發的狀態，回傳 kitty 物件（尚未關閉）"""
    rm = pyvisa.ResourceManager()
    kitty = rm.open_resource(KITTY_RESOURCE)
    kitty.timeout = KITTY_TIMEOUT_MS

    kitty.write("*RST")
    kitty.write("*CLS")  # 清空錯誤佇列，確保之後查到的都是這次執行產生的
    kitty.write(":SENS:FUNC:CONC OFF")
    kitty.write(":SOUR:FUNC VOLT")
    kitty.write(":SENS:FUNC 'CURR:DC'")
    kitty.write(":SENS:CURR:PROT 1E-3")

    kitty.write(":SOUR:VOLT:START -0.5")
    kitty.write(":SOUR:VOLT:STOP 3")
    kitty.write(":SOUR:VOLT:STEP 0.1")
    kitty.write(":SOUR:VOLT:MODE SWE")
    kitty.write(":SOUR:SWE:RANG AUTO")
    kitty.write(":SOUR:SWE:SPAC LIN")
    kitty.write(":SOUR:DEL 0.05")

    points = int(kitty.query(":SOUR:SWE:POIN?"))
    kitty.write(f":TRIG:COUN {points}")

    kitty.write(":ARM:SOUR NST")
    kitty.write(":FORM:ELEM VOLT,CURR,TIME")

    kitty.write(":OUTP ON")
    # 不再呼叫 :INIT，讓 :READ?（在 _wait_kitty_result 裡）自己處理
    # 啟動＋等待 SOT 觸發＋量測＋取值，整個流程交給同一個指令完成，
    # 避免跟我們手動呼叫的 :INIT 重複啟動、互相干擾。
    return kitty


def _wait_kitty_result(kitty):
    """
    卡住直到 kitty 完成觸發＋掃描，回傳原始資料字串與錯誤查詢結果。

    掃描結束後，額外送出一個標記脈衝：關閉 1 秒 → 固定輸出 3V 維持 0.5 秒 → 關閉。
    這個脈衝是瞬間方波，在 PV 資料裡會是一個很銳利、容易精確定位的尖峰，
    比「LED 慢慢導通」那種漸進式變化更適合拿來當時間軸校準的錨點。
    """
    try:
        raw = kitty.query(":READ?")
        error = kitty.query(":SYST:ERR?")

        # 標記脈衝
        kitty.write(":OUTP OFF")
        time.sleep(1)
        kitty.write(":SOUR:VOLT:MODE FIXED")
        kitty.write(":SOUR:VOLT:LEV 3")
        kitty.write(":OUTP ON")
        time.sleep(0.5)
        kitty.write(":OUTP OFF")

        return raw, error
    finally:
        kitty.write(":OUTP OFF")
        outp_state = kitty.query(":OUTP?")
        print(f"[kitty] 已送出 :OUTP OFF，查詢輸出狀態: {outp_state.strip()}")
        kitty.close()


def _send_trigger_pulse():
    with nidaqmx.Task() as task:
        task.do_channels.add_do_chan(f"{dev_name}/{TRIGGER_LINE}")
        task.write(True)
        task.write(False)  # 下降緣，同時送到 P0.0 與 kitty SOT
        task.write(True)


def _arm_ai_task():
    """設定 6211 AI1 為 start trigger 待命，回傳仍在開啟狀態的 task 物件"""
    ai_task = nidaqmx.Task()
    ai_task.ai_channels.add_ai_voltage_chan(
        f"{dev_name}/ai1",
        terminal_config=TerminalConfiguration.RSE,
        min_val=-1,
        max_val=1,
    )
    ai_task.timing.cfg_samp_clk_timing(
        SAMPLE_RATE,
        sample_mode=AcquisitionType.FINITE,
        samps_per_chan=TOTAL_SAMPLES,
    )
    ai_task.triggers.start_trigger.cfg_dig_edge_start_trig(
        TRIGGER_INPUT,
        trigger_edge=Edge.FALLING,
    )
    ai_task.start()  # 進入待命，這行不會卡住
    return ai_task


def _read_ai_task(ai_task):
    """卡住直到 6211 錄滿設定的秒數，回傳資料；不管 kitty 那邊狀況如何"""
    try:
        return ai_task.read(
            number_of_samples_per_channel=TOTAL_SAMPLES,
            timeout=DURATION_SECONDS + 20,
        )
    finally:
        ai_task.close()


def _save_jv_csv(raw):
    values = [float(x) for x in raw.strip().split(",")]
    rows = [values[i : i + 3] for i in range(0, len(values), 3)]
    filename = file_create.get_next_filename(prefix="jv_sweep")
    with open(filename, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Voltage (V)", "Current (A)", "Timestamp (s)"])
        writer.writerows(rows)
    return filename, len(rows)


def _save_pv_csv(data):
    filename = file_create.get_next_filename(prefix="pv_triggered")
    time_axis = [i / SAMPLE_RATE for i in range(TOTAL_SAMPLES)]
    with open(filename, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Time (s)", "Voltage (V)"])
        for t, v in zip(time_axis, data):
            writer.writerow([round(t, 4), round(v, 6)])
    return filename


async def main():
    kitty = await asyncio.to_thread(_arm_kitty)
    ai_task = await asyncio.to_thread(_arm_ai_task)

    # kitty 的 :READ? 現在身兼「啟動＋等待 SOT＋量測＋取值」，
    # 必須先丟到背景開始等待，才能送觸發，不然會錯過那個瞬間
    kitty_task = asyncio.create_task(asyncio.to_thread(_wait_kitty_result, kitty))
    ai_task_future = asyncio.create_task(asyncio.to_thread(_read_ai_task, ai_task))

    await asyncio.sleep(0.5)  # 給兩邊一點時間真正進入待命狀態
    await asyncio.to_thread(_send_trigger_pulse)  # 同時觸發 P0.0 與 kitty SOT

    # kitty、6211 從這裡開始各自獨立進行，誰先做完誰先存，互不等待

    pv_data = await ai_task_future
    pv_filename = _save_pv_csv(pv_data)
    print(f"PV 資料已存至 {pv_filename}（6211 已完成，不等 kitty）")

    raw, kitty_error = await kitty_task
    jv_filename, jv_points = _save_jv_csv(raw)
    print(f"JV 資料已存至 {jv_filename}，共 {jv_points} 筆")
    print(f"kitty 錯誤查詢: {kitty_error}")

    await asyncio.to_thread(reset_voltage._reset_all_outputs, ["ao0", "ao1"])


if __name__ == "__main__":
    asyncio.run(main())
