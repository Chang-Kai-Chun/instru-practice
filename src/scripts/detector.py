import time
import csv
import nidaqmx
from nidaqmx.constants import AcquisitionType, Edge, TerminalConfiguration

from instru_practice import reset_voltage, file_create, config

dev_name = config.device_name

SAMPLE_RATE = 1000.0
DURATION_SECONDS = 50
TOTAL_SAMPLES = int(SAMPLE_RATE * DURATION_SECONDS)

TRIGGER_OUTPUT = "port1/line0"          # P1.0，輸出觸發脈衝
TRIGGER_INPUT = f"/{dev_name}/PFI0"   # P0.0，start trigger 來源


def send_trigger_pulse():
    with nidaqmx.Task() as task:
        task.do_channels.add_do_chan(f"{dev_name}/{TRIGGER_OUTPUT}")
        task.write(True)
        task.write(False)   # 下降緣，同時送到 P0.0 與 kitty
        task.write(True)


with nidaqmx.Task() as ai_task:
    ai_task.ai_channels.add_ai_voltage_chan(
        f"{dev_name}/ai1",
        terminal_config=TerminalConfiguration.RSE,
        min_val=-1,
        max_val=1,
    )
    ai_task.timing.cfg_samp_clk_timing(
        SAMPLE_RATE,
        sample_mode=AcquisitionType.FINITE,
        samps_per_chan=TOTAL_SAMPLES,
    )
    ai_task.triggers.start_trigger.cfg_dig_edge_start_trig(
        TRIGGER_INPUT,
        trigger_edge=Edge.FALLING,
    )

    ai_task.start()          # 進入待命，等待 P0.0 的下降緣
    time.sleep(0.5)          # 給任務一點時間真正進入待命狀態
    send_trigger_pulse()     # 送出觸發，P0.0 與 kitty 同時收到

    print("已觸發，開始錄製 AI1...")
    data = ai_task.read(
        number_of_samples_per_channel=TOTAL_SAMPLES,
        timeout=DURATION_SECONDS + 20,
    )

reset_voltage._reset_all_outputs(["ao0", "ao1"])

filename = file_create.get_next_filename(prefix="pv_triggered")
time_axis = [i / SAMPLE_RATE for i in range(TOTAL_SAMPLES)]  # t=0 就是觸發那一刻

with open(filename, "w", newline="") as f:
    writer = csv.writer(f)
    writer.writerow(["Time (s)", "Voltage (V)"])
    for t, v in zip(time_axis, data):
        writer.writerow([round(t, 4), round(v, 6)])

print(f"已儲存 {len(data)} 筆 PV 資料至 {filename}")
