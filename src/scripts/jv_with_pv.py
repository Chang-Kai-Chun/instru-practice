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

POINT_OVERHEAD_SECONDS = 0.07  # 每個點除了 SOURCE_DELAY 之外，額外的實測開銷
SAFETY_MARGIN_SECONDS = 3  # 餘裕秒數
# 為了讓系統自動抓秒數，需要設定我們額外需要的秒數，並且把寫死的Duration換掉


TRIGGER_LINE = "port1/line0"  # 6211 送出觸發脈衝的通道（P1.0）
TRIGGER_INPUT = f"/{dev_name}/PFI0"  # 6211 自己接收觸發的腳位（P0.0）this line is ...

KITTY_MARKER_OFF_SECONDS = 1  # 掃描結束後，先關閉輸出維持這麼久
KITTY_MARKER_LEVEL_V = 3  # 瞬間脈衝的電壓
KITTY_MARKER_ON_SECONDS = 0.5  # 瞬間脈衝維持的時間


# 計算Duration的函式
def _estimate_duration(start_v, stop_v, step_v, source_delay):
    # 這裡選用小寫是因為參數並非全域設定，只在這個函式使用，設定為小寫
    points = round(abs(stop_v - start_v) / step_v) + 1
    sweep_time = points * (source_delay + POINT_OVERHEAD_SECONDS)
    duration_time = (
        sweep_time
        + KITTY_MARKER_OFF_SECONDS
        + KITTY_MARKER_ON_SECONDS
        + SAFETY_MARGIN_SECONDS
    )
    return duration_time


def _send_trigger_pulse():
    """
    設定 6211 的 trigger
    """
    with nidaqmx.Task() as task:
        task.do_channels.add_do_chan(f"{dev_name}/{TRIGGER_LINE}")
        task.write(True)  # 先確保是高電位，避免原本就是低電位時寫不出下降緣
        task.write(False)  # 下降緣，同時送到 P0.0 與 kitty SOT
        task.write(True)


def _arm_kitty(start_v, stop_v, step_v, compliance_a, source_delay):
    """設定 kitty 為等待 SOT 觸發的狀態（還沒真的進入等待，見 _wait_kitty_result）"""
    rm = pyvisa.ResourceManager()
    kitty = rm.open_resource(jv_pv_config.KITTY_RESOURCE)
    kitty.timeout = jv_pv_config.KITTY_TIMEOUT_MS
    keithley_setting.configure_kitty(
        kitty,
        arm_source="NST",
        START_V=start_v,
        STOP_V=stop_v,
        STEP_V=step_v,
        COMPLIANCE_A=compliance_a,
        SOURCE_DELAY=source_delay,
        # 這裡大寫表示的是keithley_setting裡的參數，取代成小寫的
        # 小寫的就是從fastapi中使用者輸入得到的
    )
    return kitty


def _arm_ai_task(sample_rate, total_samples):
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
        sample_rate,
        sample_mode=AcquisitionType.FINITE,
        samps_per_chan=total_samples,
    )
    ai_task.triggers.start_trigger.cfg_dig_edge_start_trig(
        TRIGGER_INPUT,
        trigger_edge=Edge.FALLING,
    )
    ai_task.start()  # 進入待命，這行不會卡住，硬體開始等待 PFI0 的下降緣
    return ai_task


def read_kitty_result(kitty):
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


def _read_ai_task(ai_task, total_samples, duration_time):
    """卡住直到 6211 錄滿設定的秒數，回傳資料；不管 kitty 那邊狀況如何"""
    try:
        return ai_task.read(
            number_of_samples_per_channel=total_samples,
            timeout=duration_time + 10,
        )
    finally:
        ai_task.close()


async def main(START_V, STOP_V, STEP_V, COMPLIANCE_A, SOURCE_DELAY, SAMPLE_RATE):
    # 上方的這些參數會透過FastAPI傳進來
    duration_time = _estimate_duration(START_V, STOP_V, STEP_V, SOURCE_DELAY)
    # 這裡直接設定duration_time 是透過 _estimate_duration return的值，這個函式會計算出duration_time
    total_samples = int(SAMPLE_RATE * duration_time)
    kitty = await asyncio.to_thread(
        _arm_kitty, START_V, STOP_V, STEP_V, COMPLIANCE_A, SOURCE_DELAY
    )
    # 把該讓kitty待命的參數傳入_arm_kitty函式中
    ai_task = await asyncio.to_thread(_arm_ai_task, SAMPLE_RATE, total_samples)
    # 執行這行之後，同時會把SAMPLE_RATE以及total_samples傳入_arm_ai_task函式中
    # 並且設定6211的AI1為待命狀態，並且設定好SAMPLE_RATE以及total_samples

    # kitty 的 :READ? 身兼「啟動＋等待 SOT＋量測＋取值」，
    # 必須先丟到背景開始等待，才能送觸發，不然會錯過那個瞬間
    kitty_start_measure = asyncio.create_task(
        asyncio.to_thread(read_kitty_result, kitty)
    )
    daq_start_measure = asyncio.create_task(
        asyncio.to_thread(_read_ai_task, ai_task, total_samples, duration_time)
    )

    await asyncio.sleep(0.5)  # 給兩邊一點時間真正進入待命狀態
    await asyncio.to_thread(_send_trigger_pulse)  # 同時觸發 P0.0 與 kitty SOT

    # kitty、6211 從這裡開始各自獨立進行，誰先做完誰先存，互不等待

    pv_data = await daq_start_measure
    pv_filename = pv_and_jv_file_saving.save_pv_csv(
        pv_data, sample_rate=SAMPLE_RATE, prefix="pv_triggered"
    )
    # 這裡設定的SAMPLE_RATE，是從FastAPI傳入的，然後會再回傳給pv_and_jv_file_saving.save_pv_csv函式
    print(f"PV 資料已存至 {pv_filename}（6211 已完成，不等 kitty）")

    raw, kitty_error = await kitty_start_measure
    jv_filename, jv_points = pv_and_jv_file_saving.save_jv_csv(raw)
    print(f"JV 資料已存至 {jv_filename}，共 {jv_points} 筆")
    print(f"kitty 錯誤查詢: {kitty_error}")

    await asyncio.to_thread(reset_voltage._reset_all_outputs, ["ao0", "ao1"])


if __name__ == "__main__":
    asyncio.run(
        main(
            jv_pv_config.START_V,
            jv_pv_config.STOP_V,
            jv_pv_config.STEP_V,
            jv_pv_config.COMPLIANCE_A,
            jv_pv_config.SOURCE_DELAY,
            jv_pv_config.SAMPLE_RATE,
        )
    )
    # 執行main時，需要預設6個預設參數，否則會無法執行
