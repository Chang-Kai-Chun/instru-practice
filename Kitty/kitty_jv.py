import csv
import pyvisa

rm = pyvisa.ResourceManager()
kitty = rm.open_resource("GPIB0::24::INSTR")
kitty.timeout = 90000  # 90 秒，比預估的 43.6 秒留足餘裕

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
print(f"掃描點數：{points}")
kitty.write(f":TRIG:COUN {points}")

kitty.write(":FORM:ELEM VOLT,CURR,TIME")

kitty.write(":OUTP ON")
raw = kitty.query(
    ":READ?"
)  # 設定raw為原始數據，回傳的資料是逗號分隔的字串，包含電壓、電流、時間戳記
kitty.write(":OUTP OFF")

print(kitty.query(":SYST:ERR?"))  # 要求回傳是否有error
kitty.close()

# 把逗號分隔的字串，每 3 個切成一組（電壓、電流、時間戳記）
values = [float(x) for x in raw.strip().split(",")]
rows = [values[i : i + 3] for i in range(0, len(values), 3)]

filename = "jv_sweep.csv"
with open(filename, "w", newline="") as f:
    writer = csv.writer(f)
    writer.writerow(["Voltage (V)", "Current (A)", "Timestamp (s)"])
    writer.writerows(rows)

print(f"已儲存 {len(rows)} 筆資料至 {filename}")
