from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from scripts import pico_control, led_control, daq_pv, kitty_jv, jv_with_pv
from instru_package.jv_pv_project import pv_and_jv_file_saving, jv_pv_config
import asyncio, csv

app = FastAPI()
# app 是一個 FastAPI 的實例物件


# ---------------------------建立與rx的連接---------------------------
class ConnectionManager:
    def __init__(self):
        self.active: list[WebSocket] = []
        # 連線清單，讓rx可以知道目前有多少人連線，並且可以把訊息傳給所有人

    async def connect(self, websocket: WebSocket):
        # 說明websocket是WebSocket型別，就像0.005是float
        await websocket.accept()
        self.active.append(websocket)
        # 新的連線接入FastAPI，Accept後把他append到list中，這樣rx就知道有新的連線了

    def disconnect(self, websocket: WebSocket):
        self.active.remove(websocket)
        # 有連線斷開，從list刪掉

    async def broadcast(self, message: dict):
        for websocket in self.active:
            await websocket.send_json(message)


manager = ConnectionManager()
# 建立實體物件，物件內容是ConnectionManager()


@app.websocket("/ws/status")
# FastAPI與RX溝通的橋樑，當一個RX連線進來，FastAPI就會有一條ws/status
# 這條連線街上後
async def ws_status(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
            # 持續跑迴圈，目的是讓迴圈持續進行
    except WebSocketDisconnect:
        manager.disconnect(websocket)
        # 若前端中斷連線，就會觸發WebSocketDisconnect，然後把該連線從list中刪掉


# -------------------------------------------------------------------


# ---------------------------建立讓rx可以抓取數據---------------------


@app.get("/results/{filename}")
def get_result(filename: str):
    if "/" in filename or "\\" in filename or ".." in filename:
        return {"error": "invalid filename"}
        # 若檔案名稱含有上述路逕字元就報錯
    try:
        with open(filename, newline="") as f:
            reader = csv.DictReader(f)
            rows = [{k: float(v) for k, v in row.items()} for row in reader]
        return {"filename": filename, "rows": rows}
    except FileNotFoundError:
        return {"error": "file not found"}


# -------------------------------------------------------------------


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
async def start_jv_task(
    START_V: float = jv_pv_config.START_V,
    STOP_V: float = jv_pv_config.STOP_V,
    STEP_V: float = jv_pv_config.STEP_V,
    COMPLIANCE_A: float = jv_pv_config.COMPLIANCE_A,
    SOURCE_DELAY: float = jv_pv_config.SOURCE_DELAY,
):
    if kitty_lock.locked():
        return {"status": "busy", "message": "kitty 正在使用中，請稍後再試"}

    async def _run():
        async with kitty_lock:
            raw, error = await asyncio.to_thread(
                kitty_jv.run_jv_sweep_standalone,
                START_V,
                STOP_V,
                STEP_V,
                COMPLIANCE_A,
                SOURCE_DELAY,
            )
            filename, points = pv_and_jv_file_saving.save_jv_csv(raw)
            print(f"kitty 錯誤查詢: {error}")
            print(f"JV 資料已存至 {filename}，共 {points} 筆")
            # 這步只讓FastAPI可以print出量測完成的資訊與數據有幾筆
            await manager.broadcast(
                {"event": "done", "kind": "jv", "filename": filename}
            )
            # 透過這行把訊息傳給前端，告訴前端量測完成，並且附上檔案名稱

    asyncio.create_task(_run())
    return {"status": "started"}


# 6211 單獨錄製 PV（光二極體）訊號的邏輯，不牽涉觸發、不牽涉 kitty。
@app.post("/tasks/pv")
async def start_pv_task(
    duration_seconds: float = jv_pv_config.DURATION_SECONDS,
    SAMPLE_RATE: float = jv_pv_config.SAMPLE_RATE,
):
    if daq_lock.locked():
        return {"status": "busy", "message": "6211 正在使用中，請稍後再試"}

    async def _run():
        async with daq_lock:
            data = await asyncio.to_thread(
                daq_pv.record_pv_standalone,
                duration_seconds=duration_seconds,
                SAMPLE_RATE=SAMPLE_RATE,
            )
            # 使用關鍵引數，才不會因為排序而出問題
            filename = pv_and_jv_file_saving.save_pv_csv(data)
            print(f"PV 資料已存至 {filename}，共 {len(data)} 筆")
            # 這步只讓FastAPI可以print出量測完成的資訊與數據有幾筆
            await manager.broadcast(
                {"event": "done", "kind": "pv", "filename": filename}
            )
            # 透過這行把訊息傳給前端，告訴前端量測完成，並且附上檔案名稱

    asyncio.create_task(_run())
    return {"status": "started"}


# 同步進行PV以及JV，Keithley 由 6211 觸發
@app.post("/tasks/jv_pv_sync")
async def start_jv_pv_sync_task(
    START_V: float = jv_pv_config.START_V,
    STOP_V: float = jv_pv_config.STOP_V,
    STEP_V: float = jv_pv_config.STEP_V,
    COMPLIANCE_A: float = jv_pv_config.COMPLIANCE_A,
    SOURCE_DELAY: float = jv_pv_config.SOURCE_DELAY,
    SAMPLE_RATE: float = jv_pv_config.SAMPLE_RATE,
    # 這寫把各參數寫一個預設值，預設值取用config的值，然後使用者可以自行輸入參數
    # 當使用者輸入參數後，新的參數會取代進去，例如START_V=0V，使用者自行輸入的
    # 執行到下方的 jv_with_pv.main(START_V)，才會真正把使用者輸入的值傳入jv_with_pv.py檔案中
):
    if daq_lock.locked() or kitty_lock.locked():
        return {"status": "busy", "message": "6211 或 kitty 正在使用中，請稍後再試"}

    async def _run():
        async with daq_lock:  # 執行daq鎖
            async with kitty_lock:  # 執行kitty鎖
                pv_filename, jv_filename = await jv_with_pv.main(
                    # pv & jv 的檔案名稱會透過jv_with_pv.main()回傳
                    START_V,
                    STOP_V,
                    STEP_V,
                    COMPLIANCE_A,
                    SOURCE_DELAY,
                    SAMPLE_RATE,
                )
                await manager.broadcast(
                    {
                        "event": "done",
                        "kind": "jv_pv_sync",
                        "pv_filename": pv_filename,
                        "jv_filename": jv_filename,
                    }
                )
                # 會把上方使用者輸入到FastAPI的參數傳入jv_with_pv.py檔案中

    asyncio.create_task(_run())
    return {"status": "started"}
