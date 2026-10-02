from instru_package import only_led_shining_config
import nidaqmx

sample_rate = only_led_shining_config.sample_rate
dev_name = only_led_shining_config.device_name


def _read_ai_channel_data(channel, duration, sample_rate=sample_rate):
    """
    數據讀取的核心函式
    此處會決定數據讀取的間隔時間
    ai_channel 讀取指定通道，回傳資料 list

    """
    samples_per_chan = int(duration * sample_rate)
    with nidaqmx.Task() as task:
        task.ai_channels.add_ai_voltage_chan(f"{dev_name}/{channel}")
        task.timing.cfg_samp_clk_timing(sample_rate, samps_per_chan=samples_per_chan)
        data = task.read(
            number_of_samples_per_channel=samples_per_chan, timeout=duration + 5
        )
    return data
