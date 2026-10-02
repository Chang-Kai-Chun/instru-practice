import nidaqmx
from instru_package import only_led_shining_config


def _reset_all_outputs(channels, dev_name=only_led_shining_config.device_name):
    """把 AO_CHANNELS_TO_RESET 裡列出的每個 OUTPUT 通道都設定 0V。
    用 try/except 包住每一個通道，是因為就算某個通道重置失敗
    （例如裝置已經被拔掉），也不該讓其他通道的重置跟著中斷。
    """
    for channel in channels:
        # for channel 在 AO_CHANNELS_TO_RESET 這個 list 裡面每個元素跑一次迴圈
        try:
            with nidaqmx.Task() as task:
                # 使用with語法，確保 task 用完會自動關閉
                task.ao_channels.add_ao_voltage_chan(f"{dev_name}/{channel}")
                task.write(0.0)
        except nidaqmx.DaqError as error:
            print(f"重置 {channel} 時發生錯誤：{error}")
