"""
觸發 kitty 進行 JV 掃描，同時 6211 錄製 PV 訊號，兩者由同一個觸發脈衝同步啟動。
"""

import time, asyncio, pyvisa, nidaqmx
from nidaqmx.constants import AcquisitionType, Edge, TerminalConfiguration

from instru_package import reset_voltage
from instru_package.jv_pv_project import (
    jv_pv_config,
    pv_and_jv_file_saving,
    keithley_setting,
)
from scripts import kitty_jv, daq_pv


dev_name = jv_pv_config.device_name
POLL_INTERVAL_SECONDS = 0.3

POINT_OVERHEAD_SECONDS = 0.07  # 每個點除了 SOURCE_DELAY 之外，額外的實測開銷
SAFETY_MARGIN_SECONDS = 3  # 餘裕秒數
# 為了讓系統自動抓秒數，需要設定我們額外需要的秒數，並且把寫死的Duration換掉


TRIGGER_LINE = "port1/line0"  # 6211 送出觸發脈衝的通道（P1.0）
TRIGGER_INPUT = f"/{dev_name}/PFI0"  # 6211 自己接收觸發的腳位（P0.0）this line is ...

KITTY_MARKER_OFF_SECONDS = 1  # 掃描結束後，先關閉輸出維持這麼久
KITTY_MARKER_LEVEL_V = 3  # 瞬間脈衝的電壓
KITTY_MARKER_ON_SECONDS = 0.5  # 瞬間脈衝維持的時間


def estimate_duration(start_v, stop_v, step_v, source_delay):
    """計算Duration的函式"""
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


def send_trigger_pulse():
    """設定 6211 的 trigger"""
    with nidaqmx.Task() as task:
        task.do_channels.add_do_chan(f"{dev_name}/{TRIGGER_LINE}")
        task.write(True)  # 先確保是高電位，避免原本就是低電位時寫不出下降緣
        task.write(False)  # 下降緣，同時送到 P0.0 與 kitty SOT
        task.write(True)


def arm_kitty_sync_task(start_v, stop_v, step_v, compliance_a, source_delay):
    """設定 kitty 為等待 SOT 觸發的狀態（還沒真的進入等待，見 _wait_kitty_result）"""
    rm = pyvisa.ResourceManager()
    kitty = rm.open_resource(jv_pv_config.KITTY_RESOURCE)
    kitty.timeout = jv_pv_config.KITTY_TIMEOUT_MS
    points = keithley_setting.configure_kitty_for_polling(
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
    return kitty, points


def arm_daq_sync_task(sample_rate, total_samples):
    """設定 6211 AI1 為 start trigger 待命，回傳仍在開啟狀態的 task 物件"""
    ai_task = nidaqmx.Task()
    # 這個函式是其他函式的前置設定，task 要跨函式維持開啟，不能用 with
    ai_task.ai_channels.add_ai_voltage_chan(
        f"{dev_name}/{jv_pv_config.AI_CHANNEL}",
        terminal_config=TerminalConfiguration.RSE,  # 單端參考 接地做參考
        min_val=-1,
        max_val=1,
    )
    ai_task.timing.cfg_samp_clk_timing(
        sample_rate,
        sample_mode=AcquisitionType.CONTINUOUS,
        samps_per_chan=total_samples,
    )
    ai_task.triggers.start_trigger.cfg_dig_edge_start_trig(
        TRIGGER_INPUT,
        trigger_edge=Edge.FALLING,
    )
    ai_task.start()  # 進入待命，這行不會卡住，硬體開始等待 PFI0 的下降緣
    return ai_task


def finish_kitty_sync(kitty):
    """
    掃描收集完成後，先送出瞬間標記脈衝（給時間軸比對用），
    再確認關閉輸出、查詢錯誤、釋放資源。
    """
    try:
        kitty.write(":OUTP OFF")
        time.sleep(KITTY_MARKER_OFF_SECONDS)
        kitty.write(":SOUR:VOLT:MODE FIXED")
        kitty.write(f":SOUR:VOLT:LEV {KITTY_MARKER_LEVEL_V}")
        kitty.write(":OUTP ON")
        time.sleep(KITTY_MARKER_ON_SECONDS)
        kitty.write(":OUTP OFF")
        error = kitty.query(":SYST:ERR?")
        return error
    finally:
        kitty.write(":OUTP OFF")
        outp_state = kitty.query(":OUTP?")
        print(f"[kitty] 已送出 :OUTP OFF，查詢輸出狀態: {outp_state.strip()}")
        kitty.close()


def reset_outputs():
    """關閉daq 6211的輸出"""
    reset_voltage._reset_all_outputs(["ao0", "ao1"])


async def _collect_kitty(kitty, points):
    """Keithley抓數據的函式，整體邏輯與JV ONLY相同"""
    all_rows = []
    while len(all_rows) < points:
        await asyncio.sleep(POLL_INTERVAL_SECONDS)
        new_rows = await asyncio.to_thread(
            kitty_jv.poll_kitty_rows, kitty, len(all_rows)
        )
        if new_rows:
            all_rows.extend(new_rows)
            print(f"[kitty] 累積 {len(all_rows)}/{points}")
    error = await asyncio.to_thread(finish_kitty_sync, kitty)
    filename, count = pv_and_jv_file_saving.save_jv_csv_from_rows(all_rows)
    print(f"kitty 錯誤查詢: {error}")
    print(f"JV 資料已存至 {filename}，共 {count} 筆")
    return filename


async def _collect_pv(ai_task, total_samples, sample_rate):
    """6211抓數據的函式，整體邏輯與PV ONLY相同"""
    all_data = []
    chunk_samples = int(sample_rate * daq_pv.CHUNK_SECONDS)
    try:
        while len(all_data) < total_samples:
            remaining = total_samples - len(all_data)
            this_chunk = min(chunk_samples, remaining)
            chunk = await asyncio.to_thread(daq_pv.read_pv_chunk, ai_task, this_chunk)
            all_data.extend(chunk)
            print(f"[pv] 累積 {len(all_data)}/{total_samples}")
    finally:
        ai_task.close()
    filename = pv_and_jv_file_saving.save_pv_csv(
        all_data, sample_rate=sample_rate, prefix="pv_triggered"
    )
    print(f"PV 資料已存至 {filename}")
    return filename


async def run_pv_jv_withoutFASTAPI():
    START_V = jv_pv_config.START_V
    STOP_V = jv_pv_config.STOP_V
    STEP_V = jv_pv_config.STEP_V
    COMPLIANCE_A = jv_pv_config.COMPLIANCE_A
    SOURCE_DELAY = jv_pv_config.SOURCE_DELAY
    SAMPLE_RATE = jv_pv_config.SAMPLE_RATE

    duration_time = estimate_duration(START_V, STOP_V, STEP_V, SOURCE_DELAY)
    total_samples = int(SAMPLE_RATE * duration_time)
    # 把DURATION_TIME與TOTAL_SAMPLES都算好
    kitty, points = await asyncio.to_thread(
        arm_kitty_sync_task, START_V, STOP_V, STEP_V, COMPLIANCE_A, SOURCE_DELAY
    )
    ai_task = await asyncio.to_thread(arm_daq_sync_task, SAMPLE_RATE, total_samples)

    kitty_data_collection_task = asyncio.create_task(_collect_kitty(kitty, points))
    pv_data_collection_task = asyncio.create_task(
        _collect_pv(ai_task, total_samples, SAMPLE_RATE)
    )

    await asyncio.sleep(0.5)
    await asyncio.to_thread(send_trigger_pulse)

    jv_filename = await kitty_data_collection_task
    pv_filename = await pv_data_collection_task
    await asyncio.to_thread(reset_outputs)

    # 此處重點概念，kitty_data_collection_task負責建立任務，召喚_collect_kitty函式
    # await kitty_data_collection_task 負責執行
    # jv_filename=await kitty_data_collection_task 會把回傳的filename存在jv_filename
    # 才可以將jv_filename作為我們的檔名

    print(f"JV 檔案：{jv_filename}")
    print(f"PV 檔案：{pv_filename}")


if __name__ == "__main__":
    asyncio.run(run_pv_jv_withoutFASTAPI())
