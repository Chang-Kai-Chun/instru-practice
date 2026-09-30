import nidaqmx
import time

time.sleep(3)
with nidaqmx.Task() as task:
    task.do_channels.add_do_chan("Dev1/port1/line0")
    # P1.0 輸出，數位訊號只有二元不用設定大小
    task.write(True)
    input("P1.0 輸出 High")
    task.write(False)
    input("P1.0 輸出 Low")
