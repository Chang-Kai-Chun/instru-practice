"""
這個檔案不需要接任何儀器，單純用來理解 async/await 的概念。
直接執行：python async_basics.py
"""

import asyncio
import time


# ---------------------------------------------------------------------------
# 第一部分：先看「一般(同步)寫法」有什麼問題
# ---------------------------------------------------------------------------

def sync_sensor_read(name, seconds):
    """
    模擬一個「很慢的儀器讀取」，例如儀器需要 seconds 秒才能回傳資料。
    這是一般寫法(同步、blocking)：程式執行到 time.sleep() 這一行，
    整個程式就「卡住不動」，直到 seconds 秒後才會繼續往下一行執行。
    """
    print(f"[{name}] 開始讀取，預計要 {seconds} 秒...")
    time.sleep(seconds)  # 模擬硬體真的在忙、需要等待的時間
    print(f"[{name}] 讀取完成！")
    return f"{name} 的資料"


def run_sync_version():
    """
    依序讀取兩個「感測器」，一個要 2 秒、一個要 3 秒。
    因為是同步寫法，程式只能一件事做完才做下一件事，
    所以總共要花 2 + 3 = 5 秒，即使這兩個讀取其實互不相干、
    理論上可以「同時」進行。
    """
    print("\n===== 同步(sync)版本開始 =====")
    start = time.time()

    sync_sensor_read("感測器A", 2)
    sync_sensor_read("感測器B", 3)

    elapsed = time.time() - start
    print(f"===== 同步版本結束，總共花了 {elapsed:.1f} 秒 =====\n")


# ---------------------------------------------------------------------------
# 第二部分：改寫成 async 版本，讓兩件事「同時」進行
# ---------------------------------------------------------------------------

async def async_sensor_read(name, seconds):
    """
    這是同一件事的 async 版本。差異只有兩個地方：

    1. 函式定義前面多了 `async`，代表這是一個「coroutine 函式」
       （中文常翻成「協程」）。呼叫它不會馬上執行內容，而是回傳一個
       「還沒被執行」的 coroutine 物件，要靠 `await` 或事件迴圈才會真正跑。

    2. `time.sleep(seconds)` 改成 `await asyncio.sleep(seconds)`。
       這是整個 async 寫法的關鍵：`time.sleep()` 是「霸占式」的等待，
       等待的時候整個程式(包含其他工作)都不能動；
       `await asyncio.sleep()` 是「禮讓式」的等待，它會告訴背後的
       「事件迴圈(event loop)」：「我現在要等 seconds 秒，這段時間
       你可以先去處理別的工作，時間到了再回來叫醒我」。
    """
    print(f"[{name}] 開始讀取，預計要 {seconds} 秒...")
    await asyncio.sleep(seconds)
    print(f"[{name}] 讀取完成！")
    return f"{name} 的資料"


async def run_async_version():
    """
    這裡示範兩種常見的 async 用法。
    """
    print("===== async 版本開始 =====")
    start = time.time()

    # --- 用法一：asyncio.create_task() ---
    # `asyncio.create_task(...)` 會把一個 coroutine「丟給事件迴圈排程」，
    # 讓它在背景開始執行，但目前這一行程式碼本身不會停下來等它。
    # 也就是說，呼叫完這兩行之後，感測器A、感測器B「幾乎同時」開始跑。
    task_a = asyncio.create_task(async_sensor_read("感測器A", 2))
    task_b = asyncio.create_task(async_sensor_read("感測器B", 3))

    # `await task` 才是真正「暫停在這裡，等這個 task 做完」的地方。
    # 因為 task_a、task_b 早就已經在背景跑了，
    # 所以這裡等待的總時間，取決於「跑最久的那個」，而不是兩者相加。
    result_a = await task_a
    result_b = await task_b

    elapsed = time.time() - start
    print(f"拿到結果：{result_a}, {result_b}")
    print(f"===== async 版本結束，總共花了 {elapsed:.1f} 秒 =====\n")


# ---------------------------------------------------------------------------
# 第三部分：asyncio.gather() —— 上面 create_task + await 的簡化寫法
# ---------------------------------------------------------------------------

async def run_gather_version():
    """
    `asyncio.gather(coro1, coro2, ...)` 做的事情，
    其實就是「幫你把多個 coroutine 包成 task 同時丟出去，
    然後一次等全部做完」，等同於上面手動寫 create_task + await 兩次。
    寫法更精簡，回傳值會是一個 list，順序跟你傳入的順序一致。
    """
    print("===== gather 版本開始 =====")
    start = time.time()

    results = await asyncio.gather(
        async_sensor_read("感測器A", 2),
        async_sensor_read("感測器B", 3),
    )

    elapsed = time.time() - start
    print(f"拿到結果：{results}")
    print(f"===== gather 版本結束，總共花了 {elapsed:.1f} 秒 =====\n")


# ---------------------------------------------------------------------------
# 第四部分：輪詢(polling)等待某個條件成立 —— 這是第二個檔案會用到的模式
# ---------------------------------------------------------------------------

async def wait_for_flag(flag_holder, poll_interval=0.2):
    """
    模擬「不斷檢查某個狀態，直到它變成 True 為止」的輪詢寫法。
    這正是之後第二個檔案裡，「不斷讀取 P0.0 這個數位輸入腳，
    直到讀到 High(代表收到 Trigger)」會用到的邏輯結構。

    flag_holder 是一個 list，例如 [False]。用 list 包起來是因為
    Python 的函式不能直接「修改」傳進來的布林值本身，但可以修改
    list 裡面的元素，藉此讓 main() 那邊翻轉旗標時，這裡讀得到最新狀態。
    """
    print("[輪詢] 開始等待 flag 變成 True...")
    while True:
        if flag_holder[0]:
            print("[輪詢] 偵測到 flag 已經是 True，結束等待！")
            return
        # 這裡如果不是 await asyncio.sleep()，而是直接無窮迴圈檢查，
        # 會讓這個 coroutine 一直霸占事件迴圈，導致其他工作永遠沒機會執行。
        # await asyncio.sleep(poll_interval) 讓出控制權一小段時間，
        # 讓事件迴圈有機會去跑其他 coroutine(例如下面的 flip_flag_later)。
        await asyncio.sleep(poll_interval)


async def flip_flag_later(flag_holder, delay):
    """模擬「過一段時間之後，某個外部事件發生了」（例如真正接上儀器時，訊號真的來了）"""
    print(f"[事件來源] {delay} 秒後會把 flag 設成 True...")
    await asyncio.sleep(delay)
    flag_holder[0] = True
    print("[事件來源] 已經把 flag 設成 True")


async def run_polling_demo():
    """
    同時執行「輪詢等待」跟「延遲後觸發事件」這兩個 coroutine，
    藉此觀察輪詢迴圈是怎麼一邊等待、一邊還能讓其他工作正常執行的。
    """
    print("===== 輪詢(polling)示範開始 =====")
    flag = [False]

    await asyncio.gather(
        wait_for_flag(flag, poll_interval=0.2),
        flip_flag_later(flag, delay=1.5),
    )

    print("===== 輪詢示範結束 =====\n")


# ---------------------------------------------------------------------------
# 進入點
# ---------------------------------------------------------------------------

def main():
    # 第一部分是普通函式，直接呼叫即可
    run_sync_version()

    # 第二部分之後都是 async 函式(coroutine)，
    # 不能直接呼叫（呼叫了也只是拿到一個「尚未執行」的 coroutine 物件，
    # 內容不會真的跑），必須交給 `asyncio.run(...)`。
    # `asyncio.run()` 負責建立事件迴圈、把傳入的 coroutine 丟進去執行，
    # 執行完畢後再把事件迴圈關閉——這是最外層、整個程式唯一需要呼叫一次的地方。
    asyncio.run(run_async_version())
    asyncio.run(run_gather_version())
    asyncio.run(run_polling_demo())


if __name__ == "__main__":
    main()
