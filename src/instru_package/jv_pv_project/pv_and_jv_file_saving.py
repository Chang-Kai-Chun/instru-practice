"""
作為PV、JV的資料儲存 Module
"""

import csv
from instru_package import file_create
from instru_package.jv_pv_project import jv_pv_config


def save_pv_csv(
    data, sample_rate=jv_pv_config.SAMPLE_RATE, time_offset=0.0, prefix="pv"
):
    """
    存成 CSV，Time 欄位從 time_offset 開始算（預設 0 秒）。
    jv_with_pv.py 共用這個函式，傳 prefix="pv_triggered" 跟單獨執行的
    "pv" 區分開來，time_offset 固定傳 0 即可
    （因為 start trigger 本來就是從觸發那一刻才開始取樣）。
    """
    filename = file_create.get_next_filename(prefix=prefix)
    time_axis = [time_offset + i / sample_rate for i in range(len(data))]
    with open(filename, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Time (s)", "Voltage (V)"])
        for t, v in zip(time_axis, data):
            writer.writerow([round(t, 4), round(v, 6)])
    return filename


def save_jv_csv(raw):
    """把 :READ? 回傳的原始字串（電壓,電流,時間 重複排列）存成 CSV"""
    values = [float(x) for x in raw.strip().split(",")]
    rows = [values[i : i + 3] for i in range(0, len(values), 3)]
    filename = file_create.get_next_filename(prefix="jv_sweep")
    with open(filename, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Voltage (V)", "Current (A)", "Timestamp (s)"])
        writer.writerows(rows)
    return filename, len(rows)
