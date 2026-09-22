import os
import csv
import time
import nidaqmx.system
import nidaqmx
# nidaqmx 是 National Instruments 提供的 Python API，用於與 NI-DAQmx 裝置進行互動
# 我們已經安裝好驅動並且確定windows可以偵測到我們的6211了


DEVICE_NAME = "Dev1"
SAMPLE_INTERVAL = 0.3  # 每個取樣點間隔 300 ms
SAMPLE_RATE = 1 / SAMPLE_INTERVAL  # ≈ 3.33 Hz
DURATION = 12  # 每次量測總長度 (秒)


def check_device_connected():
    """確認是否有 NI-DAQmx 裝置連接，回傳 True/False"""
    system = nidaqmx.system.System.local()
    # system.devices 是一個包含所有已連接裝置的列表
    # nidaqmx 系統會自動偵測已連接的裝置，並將其列出
    devices = list(system.devices)
    for device in devices:
        print(device.name, device.product_type)
    return len(devices) > 0


def get_next_filename(prefix="test", ext="csv"):
    """test_0.csv 已存在就用 test_1.csv、test_2.csv... 依此類推"""
    i = 0
    while True:
        filename = f"{prefix}_{i}.{ext}"
        if not os.path.exists(filename):
            # os.path.exists() 用來檢查檔案是否存在，若不存在(前面有Not)就回傳 True
            return filename
        i += 1
        # i += 1 代表每次迴圈都會將 i 加 1，直到找到不存在的檔名為止


def read_ai_channel(channel, duration=DURATION):
    """讀取指定通道，回傳資料 list"""
    samples_per_chan = int(duration * SAMPLE_RATE)
    # 計算本次量測需要的測量點數，12秒*3.33Hz ≈ 40個點，要用int，因為取點不可以有小數點
    with nidaqmx.Task() as task:
        # 建立 nidaqmx.Task() 物件，本物件代表量測任務
        task.ai_channels.add_ai_voltage_chan(f"{DEVICE_NAME}/{channel}")
        # task是我們自己設定的名稱，ai_channel是nidaqmx內建的屬性，add_ai_voltage_chan()是其內建的方法
        task.timing.cfg_samp_clk_timing(SAMPLE_RATE, samps_per_chan=samples_per_chan)
        # 同上的道理
        data = task.read(
            number_of_samples_per_channel=samples_per_chan, timeout=duration + 5
        )
        # number_of_smaple_per_channel 表示儀器需要多少的量測點才會停止
        # timeout表示若超過此時間，量測將會中斷。duration 預設為10，所以要計算好timeout時間
    return data


def save_to_csv(data, filename):
    with open(filename, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["sample_index", "value"])
        for i, value in enumerate(data):
            writer.writerow([i, value])
    print(f"資料已儲存至 {filename}")


def kitty_measurement():
    """1. 進行 kitty 訊號讀取 (AI1)"""
    print("開始進行 kitty 訊號讀取...")
    data = read_ai_channel("ai1")
    filename = get_next_filename(prefix="test")
    save_to_csv(data, filename)


def pd_measurement():
    """2. 進行 pd 讀取 (AI2)"""
    print("開始進行 pd 讀取...")
    data = read_ai_channel("ai2")
    filename = get_next_filename(prefix="test")
    save_to_csv(data, filename)


def main():
    if check_device_connected():
        # 如果check_device_connected()回傳True，代表有連接儀器，才會進入這個區塊
        print("儀器連接成功，準備開始量測...")
        time.sleep(2)

        choice = input("請選擇量測種類 (1: kitty 訊號讀取, 2: pd 讀取): ")
        # choice 只
        if choice == "1":
            kitty_measurement()
        elif choice == "2":
            pd_measurement()
        else:
            print("無效的選項，請輸入 1 或 2。")
    else:
        print("未偵測到儀器連接，請檢查連線後再試一次。")


if __name__ == "__main__":
    main()
