"""
觸發 kitty 進行 JV 掃描，同時 6211 錄製 PV 訊號，兩者由同一個觸發脈衝同步啟動。
"""

import time
import asyncio
import pyvisa
import nidaqmx
from nidaqmx.constants import AcquisitionType, Edge, TerminalConfiguration

from instru_package import reset_voltage
from instru_package.jv_pv_project import (
    jv_pv_config,
    pv_and_jv_file_saving,
    keithley_setting,
)


dev_name = jv_pv_config.device_name

DURATION_SECONDS = 15  # 掃描 ~6 秒 + 標記脈衝 1.5 秒 + 餘裕
TOTAL_SAMPLES = int(jv_pv_config.SAMPLE_RATE * DURATION_SECONDS)

TRIGGER_LINE = "port1/line0"  # 6211 送出觸發脈衝的通道（P1.0）
TRIGGER_INPUT = f"/{dev_name}/PFI0"  # 6211 自己接收觸發的腳位（P0.0）this line is ...

KITTY_MARKER_OFF_SECONDS = 1  # 掃描結束後，先關閉輸出維持這麼久
KITTY_MARKER_LEVEL_V = 3  # 瞬間脈衝的電壓
KITTY_MARKER_ON_SECONDS = 0.5  # 瞬間脈衝維持的時間


def _arm_kitty():
    """設定 kitty 為等待 SOT 觸發的狀態（還沒真的進入等待，見 _wait_kitty_result）"""
    rm = pyvisa.ResourceManager()
    kitty = rm.open_resource(jv_pv_config.KITTY_RESOURCE)
    kitty.timeout = jv_pv_config.KITTY_TIMEOUT_MS
    keithley_setting.configure_kitty(kitty, arm_source="NST")
    return kitty


def _wait_kitty_result(kitty):
    """
    卡住直到 kitty 完成觸發＋掃描，回傳原始資料字串與錯誤查詢結果。

    掃描結束後，額外送出一個瞬間脈衝
    """
    try:
        raw = kitty.query(
            ":READ?"
        )  # 設定raw 資料為Keithley 回傳的資料，這行會卡住直到kitty完成掃描
        error = kitty.query(":SYST:ERR?")

        kitty.write(":OUTP OFF")  # 先把OUTPUT關閉
        time.sleep(KITTY_MARKER_OFF_SECONDS)  # 維持N時間
        kitty.write(":SOUR:VOLT:MODE FIXED")  # 設定給電壓模式為固定電壓
        kitty.write(f":SOUR:VOLT:LEV {KITTY_MARKER_LEVEL_V}")  # 設定脈衝電壓為N伏特
        kitty.write(":OUTP ON")  # 設定OUTPUT為ON，送出脈衝
        time.sleep(KITTY_MARKER_ON_SECONDS)  # 設定瞬間脈衝維持N秒
        kitty.write(":OUTP OFF")  # 設定OUTPUT為OFF，結束脈衝

        return raw, error  # 將RAW、ERROR資料回傳
        # RAW 為Keithley 回傳的資料，ERROR 為Keithley 回傳的錯誤訊息
    finally:  # 無論如何都會執行
        kitty.write(":OUTP OFF")  # 關閉OUTPUT
        outp_state = kitty.query(":OUTP?")  # 詢問Keithley OUTPUT狀態
        print(
            f"[kitty] 已送出 :OUTP OFF，查詢輸出狀態: {outp_state.strip()}"
        )  # print出來
        kitty.close()  # 關閉kitty，釋放資源


def _send_trigger_pulse():
    with nidaqmx.Task() as task:
        task.do_channels.add_do_chan(f"{dev_name}/{TRIGGER_LINE}")
        task.write(True)  # 先確保是高電位，避免原本就是低電位時寫不出下降緣
        task.write(False)  # 下降緣，同時送到 P0.0 與 kitty SOT
        task.write(True)


def _arm_ai_task():
    """設定 6211 AI1 為 start trigger 待命，回傳仍在開啟狀態的 task 物件"""
    ai_task = nidaqmx.Task()
    # 這個函式是其他函式的前置設定，task 要跨函式維持開啟，不能用 with
    ai_task.ai_channels.add_ai_voltage_chan(
        f"{dev_name}/{jv_pv_config.AI_CHANNEL}",
        terminal_config=TerminalConfiguration.RSE,
        min_val=-1,
        max_val=1,
    )
    ai_task.timing.cfg_samp_clk_timing(
        jv_pv_config.SAMPLE_RATE,
        sample_mode=AcquisitionType.FINITE,
        samps_per_chan=TOTAL_SAMPLES,
    )
    ai_task.triggers.start_trigger.cfg_dig_edge_start_trig(
        TRIGGER_INPUT,
        trigger_edge=Edge.FALLING,
    )
    ai_task.start()  # 進入待命，這行不會卡住，硬體開始等待 PFI0 的下降緣
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


async def main():
    kitty = await asyncio.to_thread(_arm_kitty)
    ai_task = await asyncio.to_thread(_arm_ai_task)  # 這行跑完，6211 真的已經在待命

    # kitty 的 :READ? 身兼「啟動＋等待 SOT＋量測＋取值」，
    # 必須先丟到背景開始等待，才能送觸發，不然會錯過那個瞬間
    kitty_task = asyncio.create_task(asyncio.to_thread(_wait_kitty_result, kitty))
    ai_task_future = asyncio.create_task(asyncio.to_thread(_read_ai_task, ai_task))

    await asyncio.sleep(0.5)  # 給兩邊一點時間真正進入待命狀態
    await asyncio.to_thread(_send_trigger_pulse)  # 同時觸發 P0.0 與 kitty SOT

    # kitty、6211 從這裡開始各自獨立進行，誰先做完誰先存，互不等待

    pv_data = await ai_task_future
    pv_filename = pv_and_jv_file_saving.save_pv_csv(pv_data, prefix="pv_triggered")
    print(f"PV 資料已存至 {pv_filename}（6211 已完成，不等 kitty）")

    raw, kitty_error = await kitty_task
    jv_filename, jv_points = pv_and_jv_file_saving.save_jv_csv(raw)
    print(f"JV 資料已存至 {jv_filename}，共 {jv_points} 筆")
    print(f"kitty 錯誤查詢: {kitty_error}")

    await asyncio.to_thread(reset_voltage._reset_all_outputs, ["ao0", "ao1"])


if __name__ == "__main__":
    asyncio.run(main())
