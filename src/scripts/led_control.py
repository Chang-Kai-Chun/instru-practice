"""
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

import nidaqmx

from instru_package import (
    config,
    file_create,
    reset_voltage,
    signal_read,
    voltage_control,
)

dev_name = config.device_name

AO1_TRIGGER_VOLTAGE = 2.0
TRIGGER_LINE = "port0/line3"  # PFI3，數位輸入，手冊上確認過方向是 In
POLL_INTERVAL = 0.1  # 每 0.1 秒讀一次 PFI3，判斷有沒有收到 Trigger

AI9_CHANNEL = "ai9"
AI9_DURATION = 5  # 秒，收到 Trigger 後要錄多久

AO0_VOLTAGE = 1.8
LED_DURATION = 8
# 送出訊號 1.8V 給LED，維持 8 秒


# ---------------------------------------------------------------------------
# async 包裝層：把上面那些「會卡住」的函式，丟進背景執行緒去跑
# ---------------------------------------------------------------------------


async def start_ao1_trigger_source():
    """
    開啟 AO1 的電壓輸出
    Turn on AO1 voltage output
    """
    print(
        f"Setting AO1 output: {AO1_TRIGGER_VOLTAGE}V（Connecting to AI9 and PFI3）..."
    )
    await asyncio.to_thread(voltage_control.analog_output, "ao1", AO1_TRIGGER_VOLTAGE)


async def wait_for_trigger():
    """
    Trigger 函式：用於接收trigger訊號，直到讀到 High 為止。
    開啟 PFI3 的數位訊號偵測
    不斷收 PFI3 的數位訊號，直到讀到 High 為止。
    這裡用一個獨立的 DI task 持續讀取，讀完不馬上關閉，
    因為輪詢期間要重複讀很多次。
    """
    print("Start PFI3 , waiting for trigger...")
    print("------------------------------------------")

    def _open_di_task():
        task = nidaqmx.Task()
        task.di_channels.add_di_chan(f"{dev_name}/{TRIGGER_LINE}")
        # di_channels 就是 digital input channel，add_di_chan() 裡面要指定 device name 與 line 接收訊號
        # 設定 Device = Dev1，設定Line = port0/line3，對應就是 PFI3
        return task  # 　把任務回傳

    di_task = await asyncio.to_thread(_open_di_task)
    # 定義新的物件 di_task，並把 _open_di_task() 丟到背景緒去跑
    try:
        while True:
            value = await asyncio.to_thread(di_task.read)
            # di_task.read() 會回傳 True/False，True = High，False = Low
            if value:
                print("Got Trigger！")
                print("------------------------------------------")
                return
            await asyncio.sleep(POLL_INTERVAL)
    finally:
        await asyncio.to_thread(di_task.close)
        # 無論如何都要關閉 task，否則會一直佔用資源


async def record_ai9_after_trigger():
    """收到 Trigger 之後，錄製 AI9 訊號 AI9_DURATION 秒"""
    print(f"Recording signal by AI9, Duration =  {AI9_DURATION} 秒")
    print("------------------------------------------")
    data = await asyncio.to_thread(
        signal_read._read_ai_channel_data, AI9_CHANNEL, AI9_DURATION
    )
    await asyncio.to_thread(voltage_control.analog_output, "ao1", 0.0)
    print(f"After {AI9_DURATION} s, AI9 measurement finished, turn off AO1")
    print("------------------------------------------")
    await asyncio.to_thread(
        file_create.save_to_csv, data, file_create.get_next_filename(prefix="ai9")
    )
    # python 會逐行執行，如果數據很大，就會脫累整個程式進行
    # 使用 await asyncio.to_thread() 把 save_to_csv() 丟到背景緒去跑，讓其他人先跑，才不會卡住
    return data
    # reture 寫在最後面，但在此程式碼，後續沒有再使用到"task"，return可有可無


async def emit_ao2():
    """AO0 輸出 1.8V，維持 LED_DURATION 秒後拉回 0V，讓 LED 只亮固定的這段時間"""
    print(f"AO0 output {AO0_VOLTAGE}V, turn on LED, Duration = {LED_DURATION} s")
    print("------------------------------------------")
    await asyncio.to_thread(voltage_control.analog_output, "ao0", AO0_VOLTAGE)

    await asyncio.sleep(LED_DURATION)
    # 等待 LED_DURATION 秒後
    print(f"After {LED_DURATION} s, turn off LED")
    print("------------------------------------------")
    await asyncio.to_thread(voltage_control.analog_output, "ao0", 0.0)


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
        reset_voltage._reset_all_outputs(["ao1", "ao0"])
        print("Setting all of AO channels on 0V")

# t=0   start_ao1_trigger_source() → AO1 寫 2V（task 立刻關閉，但電壓維持住）
# t=0   wait_for_trigger() → 幾乎瞬間偵測到 High（因為就是同一個 2V 訊號）
# t=0   gather() 同時展開：
#         record_ai9_after_trigger()：錄 AI9 5秒 → 存檔 → 把 AO1 寫回 0V（t≈5 完成）
#         emit_ao2()：AO0 寫 1.8V → sleep 8秒 → AO0 寫回 0V（t≈8 完成）
# t=8   gather() 等兩者都做完 → finally 印出「整個流程結束」
