"""
設定 Keithley 2400 的掃描參數，並回傳任務要求的掃描點數
"""

from instru_package.jv_pv_project import jv_pv_config


def configure_kitty(kitty, arm_source="IMM"):  # arm_source = "IMM" or "NST"
    kitty.write("*RST")  # 設定為初始狀態
    kitty.write("*CLS")  # 清空錯誤佇列，確保之後查到的都是這次執行產生的
    kitty.write(":SENS:FUNC:CONC OFF")
    kitty.write(":SOUR:FUNC VOLT")  # 設定輸出為"電壓"
    kitty.write(":SENS:FUNC 'CURR:DC'")  # 設定為"直流電"
    kitty.write(
        f":SENS:CURR:PROT {jv_pv_config.COMPLIANCE_A}"
    )  # 是設定電流Compliance為1mA

    kitty.write(f":SOUR:VOLT:START {jv_pv_config.START_V}")
    kitty.write(f":SOUR:VOLT:STOP {jv_pv_config.STOP_V}")
    kitty.write(f":SOUR:VOLT:STEP {jv_pv_config.STEP_V}")
    kitty.write(":SOUR:VOLT:MODE SWE")
    kitty.write(":SOUR:SWE:RANG AUTO")
    kitty.write(":SOUR:SWE:SPAC LIN")
    kitty.write(f":SOUR:DEL {jv_pv_config.SOURCE_DELAY}")

    points = int(kitty.query(":SOUR:SWE:POIN?"))
    kitty.write(f":TRIG:COUN {points}")

    kitty.write(f":ARM:SOUR {arm_source}")
    # arm_source = IMM：Arm 層不等任何訊號，立刻視為滿足條件
    # arm_source = NST：Arm 層要等 SOT 腳位出現下降緣才算滿足條件
    kitty.write(":FORM:ELEM VOLT,CURR,TIME")

    kitty.write(":OUTP ON")
    # 注意：:OUTP ON 只是打開輸出電路，不代表 kitty 已經在等待觸發，
    # 真正進入 Arm／等待狀態，要等呼叫端送出 :READ?（或舊版的 :INIT）才開始

    return points
