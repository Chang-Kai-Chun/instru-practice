import nidaqmx
from instru_package import config


def analog_output(channel, voltage, dev_name=config.device_name):
    """控制 AO 通道電壓"""
    with nidaqmx.Task() as task:
        # with 是一個單次task，完成就關閉
        task.ao_channels.add_ao_voltage_chan(f"{dev_name}/{channel}")
        # 設定寫入的device名稱與channel
        task.write(voltage)
        # 設定 task 電壓
