"""
6211 單獨錄製 PV（光二極體）訊號的邏輯，不牽涉觸發、不牽涉 kitty。
"""

import nidaqmx
from nidaqmx.constants import AcquisitionType, TerminalConfiguration

from instru_package.jv_pv_project import pv_and_jv_file_saving
from instru_package.jv_pv_project import jv_pv_config

dev_name = jv_pv_config.device_name
AI_CHANNEL = jv_pv_config.AI_CHANNEL  # Analog Input，負責收detect PV訊號的通道


def record_pv_standalone(
    SAMPLE_RATE=jv_pv_config.SAMPLE_RATE, duration_seconds=jv_pv_config.DURATION_SECONDS
):
    """單獨錄製 PV 訊號，不等待任何外部觸發，呼叫後立刻開始取樣"""
    total_samples = int(SAMPLE_RATE * duration_seconds)
    with nidaqmx.Task() as ai_task:
        ai_task.ai_channels.add_ai_voltage_chan(
            f"{dev_name}/{AI_CHANNEL}",
            terminal_config=TerminalConfiguration.RSE,  # 設定單端輸入、以AI GND做為參考
            # TerminalConfiguration.DIFF/RES,NRSE
            # 設定不同參考端，DIFF 另一條獨立的訊號做參考，NRSE 以另外AI訊號通道為參考，RSE 以 GND 為參考
            min_val=-1,
            max_val=1,  # 設定量測電壓範圍
        )
        ai_task.timing.cfg_samp_clk_timing(
            SAMPLE_RATE,
            sample_mode=AcquisitionType.FINITE,
            samps_per_chan=total_samples,
        )
        data = ai_task.read(
            number_of_samples_per_channel=total_samples,
            timeout=duration_seconds + 10,
        )
    return data


if __name__ == "__main__":
    duration_seconds = jv_pv_config.DURATION_SECONDS
    data = record_pv_standalone(duration_seconds)
    filename = pv_and_jv_file_saving.save_pv_csv(data)
    print(f"PV 資料已存至 {filename}，共 {len(data)} 筆")
