import os
import csv


def get_next_filename(prefix="test", ext="csv"):
    i = 1
    while True:
        filename = f"{prefix}_{i}.{ext}"
        if not os.path.exists(filename):
            return filename
        i += 1


def save_to_csv(data, filename):
    with open(filename, "w", newline="") as f:
        # 建立檔案為f，給等等的csv寫入器使用
        writer = csv.writer(f)
        # 建立 csv 寫入器，進行 f 的寫入
        writer.writerow(["Time (s)", "Voltage (V)"])
        # 把第一行寫入 Time 與 Voltage
        for i, value in enumerate(data, start=1):
            # 預設是 0 開始，使用 start=1 讓 sample_index 從 1 開始
            # enumerate() 會把 data 裡的每個元素依序取出，i 是索引值，value 是對應的元素值
            writer.writerow([i, round(value, 3)])
            # 使用 round 將數值四捨五入制小數點後第 n 位
    print(f"資料已儲存至 {filename}")
    print("------------------------------------------")
