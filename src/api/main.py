from fastapi import FastAPI
from scripts import pico_control, led_control, jv_pv_sequence
import asyncio

app = FastAPI()
# app 是一個 FastAPI 的實例物件

daq_lock = asyncio.Lock()
# 設定好daq_lock是asyncio.Lock()


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


@app.post("/tasks/jv_pv")
async def start_jv_pv_task():
    if daq_lock.locked():
        return {"status": "busy", "message": "6211 正在使用中，請稍後再試"}

    async def _run():
        async with daq_lock:
            await jv_pv_sequence.main()

    asyncio.create_task(_run())
    return {"status": "started"}
