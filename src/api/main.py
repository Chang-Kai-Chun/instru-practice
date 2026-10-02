from fastapi import FastAPI
from scripts import pico_control, led_control, daq_pv, kitty_jv, jv_with_pv
from instru_package.jv_pv_project import pv_and_jv_file_saving
import asyncio

app = FastAPI()
# app 是一個 FastAPI 的實例物件

daq_lock = asyncio.Lock()
# 設定好daq_lock是asyncio.Lock()
kitty_lock = asyncio.Lock()
# 設定kitty_lock是asyncio.Lock()
# lock的用意是確保儀器不會被同時使用，避免同時操作導致儀器出錯


@app.get("/")
# @　是python的修飾器(decorator)，這裡@app.get用來指定app物件的方法
# ("/") 表示app物件接下來會綁在http方法上
def read_root():
    # 單純一個def，但要注意，要在FastAPI 運行，def都要被 @app.get("/")裝飾過
    return {"message": "Hello, World!"}
    # 把上述訊息轉換成json檔，並回傳，打開FastAPI就看得到了


@app.post("/tasks/led")
async def start_led_task():
    if daq_lock.locked():
        # daq_lock 是一個 asyncio.Lock()，
        # 若有裝置正在占用本區塊，會回傳true
        return {"status": "busy", "message": "6211 正在使用中，請稍後再試"}

    async def _run():
        # 再 async def 中再次定義一個 async def 名稱是：_run
        # 稱為巢狀函式(Nested)
        # 此處要使用此方法是因為我們需要執行main，同時又要把6211鎖住，執行完又要放鎖
        # 把這工作通通丟在一個def裡面
        async with daq_lock:
            # 使用with，用完lock之後就會自動釋放鎖
            await led_control.main()

    # 上方的 _run() 函式建立完成
    asyncio.create_task(_run())
    # 使用asyncio.create_task() 把 _run() 丟到背景緒去跑
    # 其他人可以先跑
    return {"status": "started"}
    # 回傳開始執行給前端


@app.post("/tasks/pico")
async def start_pico_task():
    asyncio.create_task(pico_control.start_pi_pico())
    return {"status": "started"}


# ---------------------------
# Below is about PV measurement and JV measurement
# ---------------------------


# Keithley 單獨做JV Curve，不會透過6211 trigger，直接透過電腦給指令，因此不需要kitty在ARM狀態
@app.post("/tasks/jv")
async def start_jv_task():
    if kitty_lock.locked():
        return {"status": "busy", "message": "kitty 正在使用中，請稍後再試"}

    async def _run():
        async with kitty_lock:
            raw, error = await asyncio.to_thread(kitty_jv.run_jv_sweep_standalone)
            filename, points = pv_and_jv_file_saving.save_jv_csv(raw)
            print(f"kitty 錯誤查詢: {error}")
            print(f"JV 資料已存至 {filename}，共 {points} 筆")

    asyncio.create_task(_run())
    return {"status": "started"}


# 6211 單獨錄製 PV（光二極體）訊號的邏輯，不牽涉觸發、不牽涉 kitty。
@app.post("/tasks/pv")
async def start_pv_task(duration_seconds: float = 10):
    if daq_lock.locked():
        return {"status": "busy", "message": "6211 正在使用中，請稍後再試"}

    async def _run():
        async with daq_lock:
            data = await asyncio.to_thread(
                daq_pv.record_pv_standalone, duration_seconds
            )
            filename = pv_and_jv_file_saving.save_pv_csv(data)
            print(f"PV 資料已存至 {filename}，共 {len(data)} 筆")

    asyncio.create_task(_run())
    return {"status": "started"}


# 同步進行PV以及JV，Keithley 由 6211 觸發
@app.post("/tasks/jv_pv_sync")
async def start_jv_pv_sync_task():
    if daq_lock.locked() or kitty_lock.locked():
        return {"status": "busy", "message": "6211 或 kitty 正在使用中，請稍後再試"}

    async def _run():
        async with daq_lock:
            async with kitty_lock:
                await jv_with_pv.main()

    asyncio.create_task(_run())
    return {"status": "started"}
