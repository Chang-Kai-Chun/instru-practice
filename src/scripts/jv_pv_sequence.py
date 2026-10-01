import time
import csv
import asyncio
import nidaqmx
from nidaqmx.constants import AcquisitionType, Edge, TerminalConfiguration
import pyvisa

from instru_package import reset_voltage, file_create, config

dev_name = config.device_name

SAMPLE_RATE = 1000.0
DURATION_SECONDS = 10
TOTAL_SAMPLES = int(SAMPLE_RATE * DURATION_SECONDS)

TRIGGER_LINE = "port1/line0"
TRIGGER_INPUT = f"/{dev_name}/PFI0"

KITTY_RESOURCE = "GPIB0::24::INSTR"
KITTY_TIMEOUT_MS = 90000


def _arm_kitty():
    """設定 kitty 為等待 SOT 觸發的狀態，回傳 kitty 物件（尚未關閉）"""
    rm = pyvisa.ResourceManager()
    kitty = rm.open_resource(KITTY_RESOURCE)
    kitty.timeout = KITTY_TIMEOUT_MS

    kitty.write("*RST")
    kitty.write(":SENS:FUNC:CONC OFF")
    kitty.write(":SOUR:FUNC VOLT")
    kitty.write(":SENS:FUNC 'CURR:DC'")
    kitty.write(":SENS:CURR:PROT 1E-3")

    kitty.write(":SOUR:VOLT:START -0.5")
    kitty.write(":SOUR:VOLT:STOP 3")
    kitty.write(":SOUR:VOLT:STEP 0.1")
    kitty.write(":SOUR:VOLT:MODE SWE")
    kitty.write(":SOUR:SWE:RANG AUTO")
    kitty.write(":SOUR:SWE:SPAC LIN")
    kitty.write(":SOUR:DEL 0.05")

    points = int(kitty.query(":SOUR:SWE:POIN?"))
    kitty.write(f":TRIG:COUN {points}")

    kitty.write(":ARM:SOUR NST")
    kitty.write(":FORM:ELEM VOLT,CURR,TIME")

    kitty.write(":OUTP ON")
    kitty.write(":INIT")
    return kitty


def _wait_kitty_result(kitty):
    """卡住直到 kitty 完成觸發＋延遲＋掃描，回傳原始資料字串與錯誤查詢結果"""
    try:
        raw = kitty.query(":READ?")
        error = kitty.query(":SYST:ERR?")
        return raw, error
    finally:
        kitty.write(":OUTP OFF")
        kitty.close()


def _send_trigger_pulse():
    with nidaqmx.Task() as task:
        task.do_channels.add_do_chan(f"{dev_name}/{TRIGGER_LINE}")
        task.write(True)
        task.write(False)
        task.write(True)


def _record_pv_and_trigger():
    """設定 AI1 為 start trigger 待命，送出觸發脈衝，錄製並回傳資料"""
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

        ai_task.start()
        time.sleep(0.5)
        _send_trigger_pulse()

        data = ai_task.read(
            number_of_samples_per_channel=TOTAL_SAMPLES,
            timeout=DURATION_SECONDS + 20,
        )
    return data


def _save_jv_csv(raw):
    values = [float(x) for x in raw.strip().split(",")]
    rows = [values[i : i + 3] for i in range(0, len(values), 3)]
    filename = file_create.get_next_filename(prefix="jv_sweep")
    with open(filename, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Voltage (V)", "Current (A)", "Timestamp (s)"])
        writer.writerows(rows)
    return filename, len(rows)


def _save_pv_csv(data):
    filename = file_create.get_next_filename(prefix="pv_triggered")
    time_axis = [i / SAMPLE_RATE for i in range(TOTAL_SAMPLES)]
    with open(filename, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Time (s)", "Voltage (V)"])
        for t, v in zip(time_axis, data):
            writer.writerow([round(t, 4), round(v, 6)])
    return filename


async def main():
    kitty = await asyncio.to_thread(_arm_kitty)

    # kitty 已就緒，把它「等結果」這個會卡很久的呼叫丟到背景，
    # 讓 main() 不用等它，可以馬上去處理 6211 那邊
    kitty_result_task = asyncio.create_task(
        asyncio.to_thread(_wait_kitty_result, kitty)
    )

    pv_data = await asyncio.to_thread(_record_pv_and_trigger)

    raw, error = await kitty_result_task

    await asyncio.to_thread(reset_voltage._reset_all_outputs, ["ao0", "ao1"])

    jv_filename, jv_points = _save_jv_csv(raw)
    pv_filename = _save_pv_csv(pv_data)

    print(f"kitty 錯誤查詢: {error}")
    print(f"JV 資料已存至 {jv_filename}，共 {jv_points} 筆")
    print(f"PV 資料已存至 {pv_filename}")


if __name__ == "__main__":
    asyncio.run(main())
