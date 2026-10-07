"""
設定 Keithley 2400 的掃描參數，並回傳任務要求的掃描點數
"""

from instru_package.jv_pv_project import jv_pv_config


def configure_kitty_for_polling(
    kitty,
    arm_source="IMM",
    START_V=jv_pv_config.START_V,
    STEP_V=jv_pv_config.STEP_V,
    STOP_V=jv_pv_config.STOP_V,
    COMPLIANCE_A=jv_pv_config.COMPLIANCE_A,
    SOURCE_DELAY=jv_pv_config.SOURCE_DELAY,
):  # arm_source = "IMM" or "NST"
    kitty.write("*RST")  # 設定為初始狀態
    kitty.write("*CLS")  # 清空錯誤佇列，確保之後查到的都是這次執行產生的
    kitty.write(":SENS:FUNC:CONC OFF")
    kitty.write(":SOUR:FUNC VOLT")  # 設定輸出為"電壓"
    kitty.write(":SENS:FUNC 'CURR:DC'")  # 設定為"直流電"
    kitty.write(f":SENS:CURR:PROT {COMPLIANCE_A}")  # 是設定電流Compliance為1mA

    kitty.write(f":SOUR:VOLT:START {START_V}")
    kitty.write(f":SOUR:VOLT:STOP {STOP_V}")
    kitty.write(f":SOUR:VOLT:STEP {STEP_V}")
    kitty.write(":SOUR:VOLT:MODE SWE")
    kitty.write(":SOUR:SWE:RANG AUTO")
    kitty.write(":SOUR:SWE:SPAC LIN")
    kitty.write(f":SOUR:DEL {SOURCE_DELAY}")

    points = int(kitty.query(":SOUR:SWE:POIN?"))
    # :SOUR:SWE:POIN? 會回傳掃描點數，這個點數是由 START_V、STOP_V、STEP_V 計算出來的
    kitty.write(f":TRIG:COUN {points}")

    kitty.write(
        ":TRAC:CLE"
    )  # 清空舊的 buffer 資料，第一次執行BUFFER沒資料，但後續會跑迴圈，必須寫
    kitty.write(f":TRAC:POIN {points}")  # buffer 大小設成跟掃描點數一樣
    kitty.write(":TRAC:FEED SENS")  # buffer 存的是量測結果（電壓/電流）
    kitty.write(":TRAC:FEED:CONT NEXT")  # 開始把資料存進 buffer

    kitty.write(f":ARM:SOUR {arm_source}")
    # arm_source = IMM：Arm 層不等任何訊號，立刻視為滿足條件
    # arm_source = NST：Arm 層要等 SOT 腳位出現下降緣才算滿足條件
    kitty.write(":FORM:ELEM VOLT,CURR,TIME")

    kitty.write(":OUTP ON")
    kitty.write(":INIT")  # 啟動掃描，立刻返回，不等待掃描結束
    return points  # 把總點數回傳


def poll_point_count(kitty):
    """查詢 buffer 目前已經收集到幾筆，不會阻塞"""
    return int(kitty.query(":TRAC:POIN:ACT?"))


def fetch_buffer_rows(kitty):
    """把 buffer 目前全部的資料抓出來，依 :FORM:ELEM VOLT,CURR,TIME 的順序，每 3 個值一組"""
    raw = kitty.query(":TRAC:DATA?")  # 要求kitty回傳
    values = [float(x) for x in raw.strip().split(",")]
    return [values[i : i + 3] for i in range(0, len(values), 3)]
