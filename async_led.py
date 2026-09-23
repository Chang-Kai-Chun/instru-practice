"""
實際流程（需要接上 USB-6211 才能跑）：

1. AO1 輸出 2V —— 一條線接到 AI9（AI9 會收到這 2V 訊號），
   另一條線接到 P0.3（2V 超過數位輸入 VIH 門檻，P0.3 會被判定為 High，當作 Trigger）
2. 不斷輪詢 P0.3，直到偵測到 High（收到 Trigger）
3. 收到 Trigger 後，AI9 開始收訊號，錄 5 秒
4. 5 秒後 AI9 停止收訊號（因為是固定時長的擷取，時間到自然結束）
5. AO0 輸出 1.8V（接到 LED），同時 LED 開始發光並記錄，錄 8 秒

async 的用途：整個流程裡「AO1 要一直維持 2V 輸出」跟「同時輪詢 P0.3」
是兩件要同時進行的事，寫法上沿用 async_basics.py 裡示範的 polling 模式。
另外 nidaqmx 的函式呼叫本身是「同步(blocking)」的——它不是原生支援
async 的套件，所以要用 `asyncio.to_thread()` 把每一個 nidaqmx 呼叫
丟到背景執行緒去跑，事件迴圈才不會被卡住。
"""

import asyncio
import csv
import os

import nidaqmx


DEVICE_NAME = "Dev1"

SAMPLE_INTERVAL = 1  # 單位：秒，每個取樣點間隔 1 s
SAMPLE_RATE = 1 / SAMPLE_INTERVAL  # ≈ 1 Hz

AO1_TRIGGER_VOLTAGE = 2.0
TRIGGER_LINE = "port0/line3"  # PFI3，數位輸入，手冊上確認過方向是 In
POLL_INTERVAL = 0.1  # 每 0.1 秒讀一次 PFI3，判斷有沒有收到 Trigger

AI9_CHANNEL = "ai9"
AI9_DURATION = 5  # 秒，收到 Trigger 後要錄多久

AO0_VOLTAGE = 1.8
LED_DURATION = 8
# 送出訊號 1.8V 給LED，維持 8 秒


# ---------------------------------------------------------------------------
# 檔案輸出（跟 6211.py 裡的邏輯一樣，複製過來讓這個檔案可以獨立執行）
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# 底層、會「卡住」的 nidaqmx 操作，全部寫成一般(同步)函式，
# 之後統一用 asyncio.to_thread() 包起來呼叫
# ---------------------------------------------------------------------------


def _read_digital_line_once(task):
    """讀一次數位輸入腳目前的狀態，回傳 True/False"""
    return task.read()


def _read_ai_channel_blocking(channel, duration, sample_rate=SAMPLE_RATE):
    """固定時長的類比輸入擷取"""
    samples_per_chan = int(duration * sample_rate)
    with nidaqmx.Task() as task:
        task.ai_channels.add_ai_voltage_chan(f"{DEVICE_NAME}/{channel}")
        task.timing.cfg_samp_clk_timing(sample_rate, samps_per_chan=samples_per_chan)
        data = task.read(
            number_of_samples_per_channel=samples_per_chan, timeout=duration + 5
        )
    return data


def analog_output(channel, voltage):
    """控制 AO 通道電壓"""
    with nidaqmx.Task() as task:
        # with 是一個單次task，完成就關閉
        task.ao_channels.add_ao_voltage_chan(f"{DEVICE_NAME}/{channel}")
        # 設定寫入的device名稱與channel
        task.write(voltage)
        # 設定 task 電壓


AO_CHANNELS_TO_RESET = ["ao0", "ao1"]  # 目前程式裡有寫入過電壓的 AO 通道


def _reset_all_outputs():
    """把 AO_CHANNELS_TO_RESET 裡列出的每個 OUTPUT 通道都設定 0V。
    用 try/except 包住每一個通道，是因為就算某個通道重置失敗
    （例如裝置已經被拔掉），也不該讓其他通道的重置跟著中斷。
    """
    for channel in AO_CHANNELS_TO_RESET:
        # for channel 在 AO_CHANNELS_TO_RESET 這個 list 裡面每個元素跑一次迴圈
        try:
            with nidaqmx.Task() as task:
                # 使用with語法，確保 task 用完會自動關閉
                task.ao_channels.add_ao_voltage_chan(f"{DEVICE_NAME}/{channel}")
                task.write(0.0)
        except nidaqmx.DaqError as error:
            print(f"重置 {channel} 時發生錯誤：{error}")


# ---------------------------------------------------------------------------
# async 包裝層：把上面那些「會卡住」的函式，丟進背景執行緒去跑
# ---------------------------------------------------------------------------


async def start_ao1_trigger_source():
    """
    開啟 AO1 的電壓輸出
    """
    print(f"設定 AO1 輸出 {AO1_TRIGGER_VOLTAGE}V（同時接到 AI9 跟 P0.3）...")
    await asyncio.to_thread(analog_output, "ao1", AO1_TRIGGER_VOLTAGE)


async def wait_for_trigger():
    """
    開啟 PFI3 的數位訊號偵測
    不斷收 PFI3 的數位訊號，直到讀到 High 為止。
    這裡用一個獨立的 DI task 持續讀取，讀完不馬上關閉，
    因為輪詢期間要重複讀很多次。
    """
    print("開始接收 PFI3 等待 Trigger...")
    print("------------------------------------------")

    def _open_di_task():
        task = nidaqmx.Task()
        task.di_channels.add_di_chan(f"{DEVICE_NAME}/{TRIGGER_LINE}")
        return task

    di_task = await asyncio.to_thread(_open_di_task)
    try:
        while True:
            value = await asyncio.to_thread(_read_digital_line_once, di_task)
            if value:
                print("收到 Trigger！")
                print("------------------------------------------")
                return
            await asyncio.sleep(POLL_INTERVAL)
    finally:
        await asyncio.to_thread(di_task.close)


async def record_ai9_after_trigger():
    """收到 Trigger 之後，錄製 AI9 訊號 AI9_DURATION 秒"""
    print(f"紀錄 AI9 Duration =  {AI9_DURATION} 秒")
    print("------------------------------------------")
    data = await asyncio.to_thread(_read_ai_channel_blocking, AI9_CHANNEL, AI9_DURATION)
    await asyncio.to_thread(analog_output, "ao1", 0.0)
    print(f"經過 {AI9_DURATION} 秒後，AI9 量測結束，已關閉 AO1")
    print("------------------------------------------")
    await asyncio.to_thread(save_to_csv, data, get_next_filename(prefix="ai9"))
    # python 會逐行執行，如果數據很大，就會脫累整個程式進行
    # 使用 await asyncio.to_thread() 把 save_to_csv() 丟到背景緒去跑，讓其他人先跑，才不會卡住
    return data
    # reture 寫在最後面，但在此程式碼，後續沒有再使用到"task"，return可有可無


async def emit_ao2():
    """AO0 輸出 1.8V，維持 LED_DURATION 秒後拉回 0V，讓 LED 只亮固定的這段時間"""
    print(f"AO0 輸出 {AO0_VOLTAGE}V，點亮 LED Duration = {LED_DURATION} 秒")
    print("------------------------------------------")
    await asyncio.to_thread(analog_output, "ao0", AO0_VOLTAGE)

    await asyncio.sleep(LED_DURATION)
    # 等待 LED_DURATION 秒後
    print(f"經過 {LED_DURATION} 秒後，關閉 LED")
    print("------------------------------------------")
    await asyncio.to_thread(analog_output, "ao0", 0.0)


# ---------------------------------------------------------------------------
# 整合流程
# ---------------------------------------------------------------------------


async def main():
    await start_ao1_trigger_source()
    # 在async 中，執行都需要加上 await 或是 create_task/gather 否則無法跑
    await wait_for_trigger()
    await asyncio.gather(
        record_ai9_after_trigger(),
        emit_ao2(),
    )

    print("Finished all tasks.")
    print("------------------------------------------")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    finally:
        # 最後一道保險：就算 asyncio.run(main()) 本身被中斷
        # （例如 Ctrl+C），也用一般同步的方式再重置一次所有 AO 輸出。
        # _reset_all_outputs() 內部每個通道都有各自的 try/except，
        # 就算裝置已經拔掉、重置失敗，也不會讓這裡整個當掉。
        _reset_all_outputs()
        print("所有 AO 通道已重置為 0V")

# t=0   start_ao1_trigger_source() → AO1 寫 2V（task 立刻關閉，但電壓維持住）
# t=0   wait_for_trigger() → 幾乎瞬間偵測到 High（因為就是同一個 2V 訊號）
# t=0   gather() 同時展開：
#         record_ai9_after_trigger()：錄 AI9 5秒 → 存檔 → 把 AO1 寫回 0V（t≈5 完成）
#         emit_ao2()：AO0 寫 1.8V → sleep 8秒 → AO0 寫回 0V（t≈8 完成）
# t=8   gather() 等兩者都做完 → finally 印出「整個流程結束」
