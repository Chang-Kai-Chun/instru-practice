"""
6211 單獨錄製 PV（光二極體）訊號的邏輯，不牽涉觸發、不牽涉 kitty。
"""

import nidaqmx
from nidaqmx.constants import AcquisitionType, TerminalConfiguration

from instru_package.jv_pv_project import pv_and_jv_file_saving
from instru_package.jv_pv_project import jv_pv_config

dev_name = jv_pv_config.device_name
AI_CHANNEL = jv_pv_config.AI_CHANNEL  # Analog Input，負責收detect PV訊號的通道

CHUNK_SECONDS = 0.1  # 間隔多久傳送一次數據給電腦

# def record_pv_standalone(
#     SAMPLE_RATE=jv_pv_config.SAMPLE_RATE, duration_seconds=jv_pv_config.DURATION_SECONDS
# ):
#     """單獨錄製 PV 訊號，不等待任何外部觸發，呼叫後立刻開始取樣"""
#     total_samples = int(SAMPLE_RATE * duration_seconds)
#     with nidaqmx.Task() as ai_task:
#         ai_task.ai_channels.add_ai_voltage_chan(
#             f"{dev_name}/{AI_CHANNEL}",
#             terminal_config=TerminalConfiguration.RSE,  # 設定單端輸入、以AI GND做為參考
#             # TerminalConfiguration.DIFF/RES,NRSE
#             # 設定不同參考端，DIFF 另一條獨立的訊號做參考，NRSE 以另外AI訊號通道為參考，RSE 以 GND 為參考
#             min_val=-1,
#             max_val=1,  # 設定量測電壓範圍
#         )
#         ai_task.timing.cfg_samp_clk_timing(
#             SAMPLE_RATE,
#             sample_mode=AcquisitionType.FINITE,
#             samps_per_chan=total_samples,
#         )
#         data = ai_task.read(
#             number_of_samples_per_channel=total_samples,
#             timeout=duration_seconds + 10,
#         )
#     return data


def arm_pv_task(SAMPLE_RATE, total_samples):
    """設定好 AI 通道，讓daq保持待命狀態"""
    ai_task = nidaqmx.Task()
    ai_task.ai_channels.add_ai_voltage_chan(
        f"{dev_name}/{AI_CHANNEL}",
        terminal_config=TerminalConfiguration.RSE,  # RSE 單端參考接地 也就是以接地做為參考
        min_val=-1,
        max_val=1,
    )
    ai_task.timing.cfg_samp_clk_timing(
        SAMPLE_RATE,
        sample_mode=AcquisitionType.CONTINUOUS,  # 設定為連續取樣模式，直到task被關閉才停止
        # 若用 FINITE，則會在取樣完 total_samples 後自動停止
        samps_per_chan=total_samples,
        # CONTINUOUS 模式下，samps_per_chan 參數作為硬體所需的緩衝區大小，用來裝數據
        # 也就是持續注水的情況下，這個暫時的水池需要多大
        # 目前設定這個緩衝區與我們整個量測的數據量一樣大，一定夠用
        # FINITE 模式下，samps_per_chan 參數作為總共要取樣的數量
    )
    ai_task.start()
    return ai_task


def read_pv_chunk(ai_task, chunk_samples):
    """
    讀取資料，會抓ai_task中的緩衝區數據，當number_of_samples_per_channel=chunk_samples時
    會把資料回傳
    """
    return ai_task.read(number_of_samples_per_channel=chunk_samples)
    # number_of_samples_per_channel 是nidaqmx.Task.read()的參數，表明各通道要讀取的數據量
    # chunk_samples 是被main呼叫，從main傳入的值，表明我們要一次抓多少數據，可見main函式中的計算。
    # 如果是被jv_with_pv.py呼叫，從jv_with_pv.py中計算後傳進來的值，表明我們要一次抓多少數據。


if __name__ == "__main__":
    DURATION_SECONDS = 10  # 只有daq，直接設10秒就好
    SAMPLE_RATE = jv_pv_config.SAMPLE_RATE  # 預設值，但使用者可以從前端輸入
    total_samples = int(SAMPLE_RATE * DURATION_SECONDS)
    chunk_samples = int(SAMPLE_RATE * CHUNK_SECONDS)
    # 設定總取樣、chunk取樣，chunk表一次要傳多少數據給電腦
    ai_task = arm_pv_task(SAMPLE_RATE, total_samples)
    # 讓dqa保持待命，並且把SAMPLE_RATE、total_samples傳入
    all_data = []  # 目前的數據量，會是一個字典形式
    try:
        while len(all_data) < total_samples:  # 當目前的數據量小於總取樣量時，持續跑迴圈
            remaining = total_samples - len(all_data)
            this_chunk = min(chunk_samples, remaining)
            chunk = read_pv_chunk(ai_task, this_chunk)
            all_data.extend(chunk)
            print(f"收到 {len(chunk)} 筆，累積 {len(all_data)}/{total_samples}")
    finally:
        ai_task.close()

    filename = pv_and_jv_file_saving.save_pv_csv(all_data)
    print(f"PV 資料已存至 {filename}，共 {len(all_data)} 筆")
