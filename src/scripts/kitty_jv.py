"""
Keithey 單獨做JV Curve，不會透過6211 trigger，直接透過電腦給指令，因此不需要kitty在ARM狀態
"""

import pyvisa

from instru_package.jv_pv_project import (
    pv_and_jv_file_saving,
    jv_pv_config,
    keithley_setting,
)


def run_jv_sweep_standalone():
    """單獨執行一次 JV 掃描，不等待任何外部觸發，呼叫後立刻開始"""
    rm = pyvisa.ResourceManager()
    kitty = rm.open_resource(jv_pv_config.KITTY_RESOURCE)
    kitty.timeout = jv_pv_config.KITTY_TIMEOUT_MS

    keithley_setting.configure_kitty(kitty, arm_source="IMM")

    try:
        raw = kitty.query(":READ?")
        error = kitty.query(":SYST:ERR?")
        return raw, error
    finally:
        kitty.write(":OUTP OFF")
        kitty.close()


if __name__ == "__main__":
    raw, error = run_jv_sweep_standalone()
    filename, points = pv_and_jv_file_saving.save_jv_csv(raw)
    print(f"kitty 錯誤查詢: {error}")
    print(f"JV 資料已存至 {filename}，共 {points} 筆")
