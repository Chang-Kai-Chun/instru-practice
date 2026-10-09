"""
Keithley 單獨做JV Curve，不會透過6211 trigger，直接透過電腦給指令，因此不需要kitty在ARM狀態
"""

import pyvisa, time

from instru_package.jv_pv_project import (
    pv_and_jv_file_saving,
    jv_pv_config,
    keithley_setting,
)


def arm_kitty_polling(
    START_V: float = jv_pv_config.START_V,
    STOP_V: float = jv_pv_config.STOP_V,
    STEP_V: float = jv_pv_config.STEP_V,
    COMPLIANCE_A: float = jv_pv_config.COMPLIANCE_A,
    SOURCE_DELAY: float = jv_pv_config.SOURCE_DELAY,
):
    """執行 JV 掃描，透過輪詢的方式等待掃描結束"""
    rm = pyvisa.ResourceManager()
    kitty = rm.open_resource(jv_pv_config.KITTY_RESOURCE)
    kitty.timeout = jv_pv_config.KITTY_TIMEOUT_MS
    points = keithley_setting.configure_kitty_for_polling(
        kitty,
        arm_source="IMM",
        START_V=START_V,
        STOP_V=STOP_V,
        STEP_V=STEP_V,
        COMPLIANCE_A=COMPLIANCE_A,
        SOURCE_DELAY=SOURCE_DELAY,
    )
    return kitty, points


def poll_kitty_rows(kitty, already_sent):
    """
    查一次目前 buffer 收集到幾筆，如果比 already_sent 多，
    就把「新增的那一段」抓出來回傳；沒有新資料就回傳空 list
    """
    current_count = keithley_setting.poll_point_count(kitty)
    # 在keithley_setting.py中，poll_point_count()會使用:TRAC:POIN:ACT? 語法持續查詢kitty的buffer有多少資料
    if current_count <= already_sent:
        # already_sent目前被fastapi與main召喚
        # 當我們用rx或fastapi執行，already_sent 由FastAPI 傳入 len(all_rows)
        # 如果只單純執行此檔案，則會由main傳入
        return []
    rows = keithley_setting.fetch_buffer_rows(kitty)
    return rows[already_sent:current_count]


def finish_kitty_sweep(kitty):
    """掃描收集完成後，確認關閉輸出、查詢錯誤，釋放資源"""
    try:
        error = kitty.query(":SYST:ERR?")
        return error
    finally:
        kitty.write(":OUTP OFF")
        outp_state = kitty.query(":OUTP?")
        print(f"[kitty] 已送出 :OUTP OFF，查詢輸出狀態: {outp_state.strip()}")
        kitty.close()


if __name__ == "__main__":
    kitty, points = arm_kitty_polling()
    all_rows = []
    while len(all_rows) < points:
        time.sleep(0.3)
        new_rows = poll_kitty_rows(kitty, len(all_rows))
        if new_rows:
            all_rows.extend(new_rows)
            print(f"累積 {len(all_rows)}/{points}")

    error = finish_kitty_sweep(kitty)
    filename, count = pv_and_jv_file_saving.save_jv_csv_from_rows(all_rows)
    print(f"kitty 錯誤查詢: {error}")
    print(f"JV 資料已存至 {filename}，共 {count} 筆")
