import csv
import pyvisa

rm = pyvisa.ResourceManager()
kitty = rm.open_resource("GPIB0::24::INSTR")
kitty.timeout = 90000

kitty.write("*RST")
kitty.write(":SENS:FUNC:CONC OFF")
kitty.write(":SOUR:FUNC VOLT")
kitty.write(":SENS:FUNC 'CURR:DC'")
kitty.write(":SENS:CURR:PROT 1E-3")

kitty.write(":SOUR:VOLT:START -0.5")
kitty.write(":SOUR:VOLT:STOP 3")
kitty.write(":SOUR:VOLT:STEP 0.01")
kitty.write(":SOUR:VOLT:MODE SWE")
kitty.write(":SOUR:SWE:RANG AUTO")
kitty.write(":SOUR:SWE:SPAC LIN")
kitty.write(":SOUR:DEL 0.05")

points = int(kitty.query(":SOUR:SWE:POIN?"))
kitty.write(f":TRIG:COUN {points}")

kitty.write(":ARM:SOUR NST")   # 等 SOT 下降緣
kitty.write(":TRIG:DEL 2")     # 收到觸發後，延遲 2 秒才真正開始掃描
kitty.write(":FORM:ELEM VOLT,CURR,TIME")

kitty.write(":OUTP ON")
kitty.write(":INIT")           # 進入等待狀態，準備好接收 SOT

print("kitty 已就緒，等待 6211 發出觸發...")
raw = kitty.query(":READ?")    # 這裡會卡住，直到觸發到來、掃描完成
kitty.write(":OUTP OFF")

print(kitty.query(":SYST:ERR?"))
kitty.close()

values = [float(x) for x in raw.strip().split(",")]
rows = [values[i:i + 3] for i in range(0, len(values), 3)]

with open("jv_sweep_triggered.csv", "w", newline="") as f:
    writer = csv.writer(f)
    writer.writerow(["Voltage (V)", "Current (A)", "Timestamp (s)"])
    writer.writerows(rows)

print(f"已儲存 {len(rows)} 筆 JV 資料")
