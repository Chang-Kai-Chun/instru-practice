import pyvisa

rm = pyvisa.ResourceManager()
kitty = rm.open_resource("GPIB0::24::INSTR")
kitty.timeout = 10000

kitty.write("*RST")  # 把儀器回到預設狀態，所有動作的第一步
kitty.write(":SOUR:FUNC VOLT")  # 設定功能為電壓
kitty.write(":SOUR:VOLT:MODE FIXED")  # 電壓模式為固定，非掃描
kitty.write(":SOUR:VOLT:RANG 20")  # 設定範圍是20
kitty.write(":SOUR:VOLT:LEV 3.0")  # 設定輸出電壓是 3.0 V
kitty.write(":SENS:CURR:PROT 1E-3")  # 設定電流上限是 1 mA
kitty.write(':SENS:FUNC "CURR"')  # 設定量測功能為電流
kitty.write(":SENS:CURR:RANG 1E-3")  # 設定量測電流範圍是 1 mA
kitty.write(":FORM:ELEM CURR")  # 設定回傳資料的格式是電流
kitty.write(":ARM:SOUR NST")  # 等 SOT 被拉低才開始
kitty.write(":ARM:COUN 1")
kitty.write(":TRIG:COUN 1")
kitty.write(":OUTP ON")
kitty.write(":INIT")  # 讓 kitty 離開閒置狀態，進入等待
input("觀察 kitty 面板，確認後按 Enter 中止...")
kitty.write(":ABOR")  # 終止
kitty.write(":OUTP OFF")  # 關閉輸出
print(kitty.query(":SYST:ERR?"))
kitty.close()
