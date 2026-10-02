"""
claude寫好的，不要改動

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

from instru_package import only_led_shining_config, reset_voltage, file_create

dev_name = only_led_shining_config.device_name

SAMPLE_RATE = 1000.0
DURATION_SECONDS = 15  # 掃描 ~6 秒 + 標記脈衝 1.5 秒 + 餘裕
TOTAL_SAMPLES = int(SAMPLE_RATE * DURATION_SECONDS)  # 1000/秒 * 15 秒 = 15000 點

TRIGGER_LINE = "port1/line0"  # 設定trigger output的通道
TRIGGER_INPUT = f"/{dev_name}/PFI0"  # trigger input的通道

KITTY_RESOURCE = "GPIB0::24::INSTR"  # 設定keithley的GPIB位址
KITTY_TIMEOUT_MS = 90000  # 設定Keithley的timeout時間，要長於整個掃描時間


def _arm_kitty():
    """設定 kitty 為等待 SOT 觸發的狀態，回傳 kitty 物件（尚未關閉）"""
    rm = pyvisa.ResourceManager()
    kitty = rm.open_resource(KITTY_RESOURCE)
    kitty.timeout = KITTY_TIMEOUT_MS

    kitty.write("*RST")  # 重設Keithley
    kitty.write("*CLS")  # 清空錯誤佇列，確保之後回報內容都是這次執行產生的
    kitty.write(":SENS:FUNC:CONC OFF")
    kitty.write(":SOUR:FUNC VOLT")  # 設定輸出為"電壓"
    kitty.write(":SENS:FUNC 'CURR:DC'")  # 設定為"直流電"
    kitty.write(":SENS:CURR:PROT 1E-3")  # 設定電流Compliance為1mA，避免燒壞元件

    kitty.write(":SOUR:VOLT:START -0.5")  # 設定起始為 -0.5V
    kitty.write(":SOUR:VOLT:STOP 3")  # 設定結束為 3V
    kitty.write(":SOUR:VOLT:STEP 0.1")  # 設定步進為 0.1V
    kitty.write(":SOUR:VOLT:MODE SWE")  # 設定為掃描模式
    kitty.write(":SOUR:SWE:RANG AUTO")  # 設定掃描範圍為自動
    kitty.write(":SOUR:SWE:SPAC LIN")  # 設定掃描間距為線性
    kitty.write(":SOUR:DEL 0.05")  # 設定每個點之間的時間為 50ms

    points = int(kitty.query(":SOUR:SWE:POIN?"))  # 設定points，且為int型態
    # 利用query，要求kitty做回傳，
    kitty.write(f":TRIG:COUN {points}")
    # TRIG:COUN 表示Trigger 層要執行幾次，我們設定{points}，也就是本次掃描的點數
    # 所以keithley 就會自動執行trigger層 {points}次

    kitty.write(":ARM:SOUR NST")
    # :ARM:SOUR 表示ARM層要等待什麼樣的訊號才算滿足條件，繼續往下執行
    # NST(NSTest)，表示SOT訊號由高電位轉為低電位這個行為等於滿足條件
    kitty.write(":FORM:ELEM VOLT,CURR,TIME")  # 設定資料儲存為電壓、電流、時間

    kitty.write(":OUTP ON")
    # 最後一條指令，把所有kitty需要的設定寫入
    return kitty
    # 把設定好的kitty回傳，可以讓wait_kitty_result()去做 :READ?，也可以讓main()去做 :SYST:ERR?，最後再關閉kitty


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
        kitty.write(":OUTP OFF")  # 設定OUTPUT OFF
        time.sleep(1)  # 持續 1 秒
        kitty.write(":SOUR:VOLT:MODE FIXED")  # 設定電壓為固定模式
        kitty.write(":SOUR:VOLT:LEV 3")  # 設定電壓輸出為 3 V
        kitty.write(":OUTP ON")  # 設定OUTPUT ON
        time.sleep(0.5)  # 持續 0.5 秒
        kitty.write(":OUTP OFF")  # 設定OUTPUT OFF

        return raw, error
        # 把RAW、ERROR資料回傳(這兩個是變數，由kitty接收的資料以及錯誤訊息)
    finally:  # finally 表示無論如何都會執行，確保 kitty 最後一定會關閉
        kitty.write(":OUTP OFF")  # 　設定 OUTPUT OFF
        outp_state = kitty.query(
            ":OUTP?"
        )  # 要求Keithley回傳OUTPUT狀態，確認是否真的關閉
        print(
            f"[kitty] 已送出 :OUTP OFF，查詢輸出狀態: {outp_state.strip()}"
        )  # print出實際訊息
        kitty.close()  # 關閉kitty，釋放資源


def _send_trigger_pulse():
    with nidaqmx.Task() as task:  # 用with as 確保任務結束自動釋放資源
        task.do_channels.add_do_chan(f"{dev_name}/{TRIGGER_LINE}")  # 設定裝置名以及通道
        task.write(True)  # 設定初始狀態為高電位，避免一開始就觸發
        task.write(False)  # 下降緣，同時送到 P0.0 與 kitty SOT
        task.write(True)


def _arm_ai_task():
    """設定 6211 AI1 為 start trigger 待命，回傳仍在開啟狀態的 task 物件"""
    ai_task = nidaqmx.Task()  # 設定Analog Input任務
    # 由於這個函式做為其他函式的前置設定，其他函式會讀取他，所以不可以用with as
    ai_task.ai_channels.add_ai_voltage_chan(  # 設定analog input通道
        f"{dev_name}/ai1",
        terminal_config=TerminalConfiguration.RSE,  # 設定單端輸入、以AI GND做為參考
        min_val=-1,
        max_val=1,  # 設定量測範圍為 -1V ~ 1V
    )
    ai_task.timing.cfg_samp_clk_timing(  # 設定取樣時鐘
        SAMPLE_RATE,  # 設定取樣率為 1000Hz (每秒取樣 1000 次)
        sample_mode=AcquisitionType.FINITE,  # 設定取樣模式為有限，當取樣數量達到設定就停止
        # nidaqmx 也提供無限取樣，會持續取樣直到我們使用 ai_task.stop() 停止，或是程式結束
        samps_per_chan=TOTAL_SAMPLES,  # 設定我們的取樣數等於多少
        # TOTAL_SAMPLES = SAMPLE_RATE * DURATION_SECONDS
        # 1000點/秒 * 15秒 = 15000點
    )
    ai_task.triggers.start_trigger.cfg_dig_edge_start_trig(  # 設定trigger觸發機制
        TRIGGER_INPUT,  # 我們設定的TRIGGER_INPUT = P0.0
        trigger_edge=Edge.FALLING,  # 設定trigger_edge為下降緣，也就是P0.0由高轉低時，表示為Trigger來了
    )
    ai_task.start()
    # 把ai_task啟動，進入等待trigger的狀態，等到P0.0下降緣時，才會開始取樣
    # 上方這些也是在設定ai_task的任務設定
    return ai_task  # 設定好之後把ai_task回傳，讓其他函式可以使用


def _read_ai_task(ai_task):
    """卡住直到 6211 錄滿設定的秒數，回傳資料；不管 kitty 那邊狀況如何"""
    try:
        return ai_task.read(
            number_of_samples_per_channel=TOTAL_SAMPLES,
            timeout=DURATION_SECONDS + 20,  # 最多等待 DURATION_SECONDS + 20 秒
            # 如果超過時間，就會丟出 nidaqmx.errors.DaqError，程式會中斷
        )
    finally:  # 無論如何都會執行
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
    kitty = await asyncio.to_thread(_arm_kitty)  # 設定好kitty 處在arm
    ai_6211_task = await asyncio.to_thread(_arm_ai_task)  # 設定好6211 處在arm

    # kitty 的 :READ? 現在身兼「啟動＋等待 SOT＋量測＋取值」，
    # 必須先丟到背景開始等待，才能送觸發，不然會錯過那個瞬間
    kitty_task = asyncio.create_task(asyncio.to_thread(_wait_kitty_result, kitty))
    ai_task_future = asyncio.create_task(asyncio.to_thread(_read_ai_task, ai_6211_task))

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
