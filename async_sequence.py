"""
實際流程（需要接上 USB-6211 才能跑）：

1. AO1 輸出 2V —— 一條線接到 AI9（AI9 會收到這 2V 訊號），
   另一條線接到 P0.3（2V 超過數位輸入 VIH 門檻，P0.3 會被判定為 High，當作 Trigger）
2. 不斷輪詢 P0.3，直到偵測到 High（收到 Trigger）
3. 收到 Trigger 後，AI9 開始收訊號，錄 5 秒
4. 5 秒後 AI9 停止收訊號（因為是固定時長的擷取，時間到自然結束）
5. AO0 輸出 3V（接到 AI10），同時 AI10 開始收訊號並記錄，錄 8 秒

async 的用途：整個流程裡「AO1 要一直維持 2V 輸出」跟「同時輪詢 P0.3」
是兩件要同時進行的事，寫法上沿用 async_basics.py 裡示範的 polling 模式。
另外 nidaqmx 的函式呼叫本身是「同步(blocking)」的——它不是原生支援
async 的套件，所以要用 `asyncio.to_thread()` 把每一個 nidaqmx 呼叫
丟到背景執行緒去跑，事件迴圈才不會被卡住。
"""

import asyncio
import csv
import os
import time

import nidaqmx


DEVICE_NAME = "Dev1"

SAMPLE_INTERVAL = 1  # 單位：秒，每個取樣點間隔 300 ms，跟 6211.py 一致
SAMPLE_RATE = 1 / SAMPLE_INTERVAL  # ≈ 3.33 Hz

AO1_TRIGGER_VOLTAGE = 2.0
TRIGGER_LINE = "port0/line3"  # P0.0，數位輸入，手冊上確認過方向是 In
POLL_INTERVAL = 0.1  # 每 0.1 秒讀一次 P0.0，判斷有沒有收到 Trigger

AI9_CHANNEL = "ai9"
AI9_DURATION = 5  # 秒，收到 Trigger 後要錄多久

AO0_VOLTAGE = 3.0
AI10_CHANNEL = "ai10"
AI10_DURATION = 8
# 送出訊號3V給AI10，維持8秒


# ---------------------------------------------------------------------------
# 檔案輸出（跟 6211.py 裡的邏輯一樣，複製過來讓這個檔案可以獨立執行）
# ---------------------------------------------------------------------------


def get_next_filename(prefix="test", ext="csv"):
    i = 0
    while True:
        filename = f"{prefix}_{i}.{ext}"
        if not os.path.exists(filename):
            return filename
        i += 1


def save_to_csv(data, filename):
    with open(filename, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["sample_index", "value"])
        for i, value in enumerate(data):
            writer.writerow([i, value])
    print(f"資料已儲存至 {filename}")


# ---------------------------------------------------------------------------
# 底層、會「卡住」的 nidaqmx 操作，全部寫成一般(同步)函式，
# 之後統一用 asyncio.to_thread() 包起來呼叫
# ---------------------------------------------------------------------------


def _open_ao_task_and_write(channel, voltage):
    """開一個 AO task、寫入電壓，但『不關閉』task 就回傳它。
    刻意不關閉是因為：task 一旦關閉，這條線的輸出行為手冊沒有明確保證會怎樣，
    我們需要這個輸出通道在對應的 AI 通道收訊號的整段時間內持續輸出指定電壓，
    所以要讓 task 保持開啟（目前用來讓 AO1 在 AI9 收訊號期間持續輸出 2V）。
    """
    task = nidaqmx.Task()
    # task 是我們設定的物件，.Task() 是 nidaqmx 這個 module 內建的類別(class)，代表一個量測任務
    task.ao_channels.add_ao_voltage_chan(f"{DEVICE_NAME}/{channel}")
    task.write(voltage)
    return task


def _close_ao_task(task, reset_to_zero=True):
    if reset_to_zero:
        task.write(0.0)
    task.close()


def _read_digital_line_once(task):
    """讀一次數位輸入腳目前的狀態，回傳 True/False"""
    return task.read()


def _read_ai_channel_blocking(channel, duration, sample_rate=SAMPLE_RATE):
    """跟 6211.py 的 read_ai_channel() 邏輯相同：固定時長的類比輸入擷取"""
    samples_per_chan = int(duration * sample_rate)
    with nidaqmx.Task() as task:
        task.ai_channels.add_ai_voltage_chan(f"{DEVICE_NAME}/{channel}")
        task.timing.cfg_samp_clk_timing(sample_rate, samps_per_chan=samples_per_chan)
        data = task.read(
            number_of_samples_per_channel=samples_per_chan, timeout=duration + 5
        )
    return data


def _write_ao_voltage_blocking(channel, voltage):
    """單次寫入 AO 電壓，寫完馬上關閉 task（目前用來讓 AO0 輸出 3V，不需要跟 AO1 一樣保持開啟）"""
    with nidaqmx.Task() as task:
        task.ao_channels.add_ao_voltage_chan(f"{DEVICE_NAME}/{channel}")
        task.write(voltage)


# ---------------------------------------------------------------------------
# async 包裝層：把上面那些「會卡住」的函式，丟進背景執行緒去跑
# ---------------------------------------------------------------------------


async def start_ao1_trigger_source():
    """開始輸出 AO1 = 2V，回傳仍在開啟狀態的 task 物件，之後要自己負責關閉"""
    print(f"設定 AO1 輸出 {AO1_TRIGGER_VOLTAGE}V（同時接到 AI9 跟 P0.3）...")
    task = await asyncio.to_thread(_open_ao_task_and_write, "ao1", AO1_TRIGGER_VOLTAGE)
    return task


async def wait_for_trigger():
    """
    不斷輪詢 P0.3 直到讀到 High 為止。
    這裡用一個獨立的 DI task 持續讀取，讀完不馬上關閉，
    因為輪詢期間要重複讀很多次。
    """
    print("開始輪詢 P0.3 等待 Trigger...")

    def _open_di_task():
        task = nidaqmx.Task()
        task.di_channels.add_di_chan(f"{DEVICE_NAME}/{TRIGGER_LINE}")
        return task

    di_task = await asyncio.to_thread(_open_di_task)
    try:
        while True:
            value = await asyncio.to_thread(_read_digital_line_once, di_task)
            if value:
                print("偵測到 P0.3 = High，收到 Trigger！")
                return
            await asyncio.sleep(POLL_INTERVAL)
    finally:
        await asyncio.to_thread(di_task.close)


async def record_ai9_after_trigger():
    """收到 Trigger 之後，錄製 AI9 訊號 AI9_DURATION 秒"""
    print(f"開始錄製 AI9，時長 {AI9_DURATION} 秒...")
    data = await asyncio.to_thread(_read_ai_channel_blocking, AI9_CHANNEL, AI9_DURATION)
    print("AI9 錄製結束（時間到，自然停止）")
    return data


async def emit_ao2_and_record_ai2():
    """AO0 輸出 3V 同時開始錄製 AI10 兩者同步開始"""
    print(f"AO0 輸出 {AO0_VOLTAGE}V 同時開始錄製 AI10（{AI10_DURATION} 秒）...")

    # asyncio.gather 會把這兩個 coroutine 同時丟進事件迴圈，
    # 「幾乎同時」開始執行，藉此達到使用者要求的『同步開始』。
    # 兩者背後其實各自跑在不同的背景執行緒裡，所以不會互相卡住。
    _, ai10_data = await asyncio.gather(
        asyncio.to_thread(_write_ao_voltage_blocking, "ao0", AO0_VOLTAGE),
        asyncio.to_thread(_read_ai_channel_blocking, AI10_CHANNEL, AI10_DURATION),
    )
    print("AI10 錄製結束")
    return ai10_data


# ---------------------------------------------------------------------------
# 整合流程
# ---------------------------------------------------------------------------


async def main():
    ao1_task = await start_ao1_trigger_source()

    try:
        await wait_for_trigger()
        ai9_data = await record_ai9_after_trigger()
    finally:
        # AI9 錄製結束後，不再需要 AO1 繼續輸出，關閉並拉回 0V
        print("關閉 AO1 輸出...")
        await asyncio.to_thread(_close_ao_task, ao1_task, True)

    save_to_csv(ai9_data, get_next_filename(prefix="ai9"))

    ai10_data = await emit_ao2_and_record_ai2()
    save_to_csv(ai10_data, get_next_filename(prefix="ai10"))

    print("整個流程結束")


if __name__ == "__main__":
    asyncio.run(main())
