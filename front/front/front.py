import reflex as rx
import httpx, websockets, json, uuid, time

FASTAPI_URL = "http://localhost:8000"
# setting FastAPI_URL
WS_URL = "ws://localhost:8000/ws/status"
# setting websocket URL, like a bridge between FastAPI and RX


def labeled_input(label: str, value, on_change) -> rx.Component:
    """
    Function: decribe the label
    建立def 未來不用每個label都打很長
    """
    return rx.vstack(
        rx.text(label, size="1", color="gray"),
        rx.input(
            value=value,
            on_change=on_change,
        ),
        spacing="1",
    )


class State(rx.State):  # every connetion own their state, it is independent
    # 先定義出一個類別為：state
    # 未來連線進來，都會建立一個獨自的state

    measurement_type: str = "jv"
    # 內容有一個measurement_type，類型是str，就是我們接下來要選的，先預設顯示為jv
    start_v: float = -0.5
    stop_v: float = 3.0
    step_v: float = 0.01
    compliance_a: float = 0.01
    sample_rate: float = 1000.0
    source_delay: float = 0.005
    status: str = "idle"  # 預設狀態

    pv_chart_data: list[dict] = []
    jv_chart_data: list[dict] = []
    # 先設定空list，內部元素為字典，未來存放我們的數據

    _is_listening: bool = False
    # 設定監聽狀態目前為否，表示目前沒有監聽迴圈在執行

    @rx.event(background=True)  # 背景事件，讓此事件可以持續在背景運作
    async def listen_status(self):
        """
        持續監聽 FastAPI 的 /ws/status，即時把收到的量測資料更新進圖表。
        """

        # -----輔助監控工具-----
        listener_id = uuid.uuid4().hex[:8]  # 生成8碼隨機碼
        print(f"[listen_status] 啟動，id={listener_id}")
        # 新裝置連線進來，觸發listener，就會print告訴我們新連線

        async with self:
            if self._is_listening:
                return
            # 若已經有一個監聽迴圈在跑了，直接return空白
            self._is_listening = True
            # 如果沒有監聽迴圈在跑，打開

        local_pv_buffer = []  # 設定緩衝區為空白
        pv_total_received = 0  # 設定pv目前接收到的資料
        last_pv_flush = time.time()  # 紀錄現在時間
        FLUSH_INTERVAL = 0.1  # 畫面最多每 0.1 秒更新一次，不管資料送進來多勤

        async with websockets.connect(WS_URL) as ws:
            # 使用websocket連線到FastAPI，網址為WS_URL
            async for message in ws:
                # 設定迴圈，當收到訊息，就把message放入data(json格式)
                # message 作為迴圈變數，就像是 for i in list...
                data = json.loads(message)
                # print(
                #     f"[Reflex {time.time():.2f}] 收到訊息: {data['event']}, kind={data.get('kind')}"
                # )
                # 讓迴圈內的print一直跑，可以讓rx terminal顯示是否有成功收到訊息，且其接收到的時間戳記、資料內容、測量種類

                # -----設定當量測條件等於pv，執行：-----
                if data["event"] == "processing" and data["kind"] == "pv":
                    # 當本次傳送的數據資料等於量測的部分數據
                    # 同時滿足量測種類是pv，才會進入這個條件
                    new_points = [
                        {
                            "time_second": (pv_total_received + i) / self.sample_rate,
                            "voltage": v,  # new_points 接收的資料會有:時間 (s)以及 電壓 (V)
                        }
                        for i, v in enumerate(data["chunk"])
                        # 設定index=start_index+i，這樣就會依序增加，/self.sample_rate，就是把點數變成秒數，v 就是data["chunk"]內的數據，這裡是電壓值
                    ]  # new_points 是一個list，拿來裝收到的數據，每次收到的會是一個chunk，直接把new_points這個list取代成下一個chunk的資料
                    pv_total_received += len(new_points)
                    # pv_total_received 一開始設定為零，使用+=可以累加，i+=1 就是 i = i + 1 的意思
                    local_pv_buffer.extend(new_points)  # 把新資料存進去緩衝區裡面

                    now = time.time()
                    if now - last_pv_flush >= FLUSH_INTERVAL:
                        # 當現在時間與上次刷新時間已經相差 FLUSH_INTERVAL秒，就執行：
                        async with self:
                            self.pv_chart_data.extend(
                                local_pv_buffer
                            )  # 把緩衝區的資料存進去pv_chaart_data
                        local_pv_buffer = []
                        # 把緩衝區設為0，才不會重複寫入
                        last_pv_flush = now
                        # 把這次的刷新時間記錄下來，下一次刷新才可以比較

                # -----設定當量測條件等於jv，執行：-----
                elif data["event"] == "processing" and data["kind"] == "jv":
                    async with self:
                        new_points = [
                            {"voltage": row[0], "current": row[1]}
                            # 在keithley輸出的csv檔案中row1是電壓，row2是電流，row3是時間戳記
                            # row[0]就是row1、row[1]就是row2，因為python計數是從0開始
                            for row in data["chunk"]
                        ]
                        self.jv_chart_data.extend(new_points)

                elif data["event"] == "done":
                    async with self:
                        if (
                            local_pv_buffer
                        ):  # 有數值就是true，就會把數據加入到pv_chart_data的後方做延伸
                            self.pv_chart_data.extend(local_pv_buffer)
                        self.status = "done"  # 無論如何都會執行：把status改為done
                    local_pv_buffer = []
                    pv_total_received = 0
                    last_pv_flush = time.time()
                    # 每次量測結束，重設這些計數器，準備好迎接下一次全新的量測

    @rx.event
    # 裝飾器，在rx，這個是用來讓此函數可以被rx呼叫的裝飾器
    def set_measurement_type(self, value: str):
        # set_measurement_type 作為rx的後端，會把改變的變數傳出去
        self.measurement_type = value
        # 設定本函數為set_measurement_type，rx呼叫時，會把value傳進來
        # 當本函數收到value例如 value="pv"，就會把measurement_type改成"pv"
        # 下方index()就會知道現在該顯示甚麼
        # 這裡的value會透過下拉選單傳回來

    @rx.event
    def set_start_v(self, value: str):
        # 使用者輸入的雖然是小數點，但rx會將使用者輸入的內容視為字串，因此資料型別是str
        self.start_v = float(value)

    @rx.event
    def set_stop_v(self, value: str):
        self.stop_v = float(value)

    @rx.event
    def set_step_v(self, value: str):
        self.step_v = float(value)

    @rx.event
    def set_compliance_a(self, value: str):
        self.compliance_a = float(value)

    @rx.event
    def set_sample_rate(self, value: str):
        self.sample_rate = float(value)

    @rx.event
    def set_source_delay(self, value: str):
        self.source_delay = float(value)

    @rx.event
    async def start_measurement(self):
        """
        設定將參數傳送給FastAPI的函數
        this function will be called when the user clicks the "Start Measurement" button in the RX frontend.
        並且呼叫FastAPI對應的def開始執行量測
        calling FastAPI's corresponding def to start the measurement.
        """
        self.status = "running"
        self.pv_chart_data = []
        self.jv_chart_data = []
        # 每次重新開始量測時，先把chart_data清空，避免上次的數據還在

        if self.measurement_type == "jv":
            url = f"{FASTAPI_URL}/tasks/jv"
            params = {
                "START_V": self.start_v,
                "STOP_V": self.stop_v,
                "STEP_V": self.step_v,
                "COMPLIANCE_A": self.compliance_a,
                "SOURCE_DELAY": self.source_delay,
            }
        elif self.measurement_type == "pv":
            url = f"{FASTAPI_URL}/tasks/pv"
            params = {
                "SAMPLE_RATE": self.sample_rate,
            }
        else:
            url = f"{FASTAPI_URL}/tasks/jv_pv_sync"
            params = {
                "START_V": self.start_v,
                "STOP_V": self.stop_v,
                "STEP_V": self.step_v,
                "COMPLIANCE_A": self.compliance_a,
                "SOURCE_DELAY": self.source_delay,
                "SAMPLE_RATE": self.sample_rate,
            }

        async with httpx.AsyncClient() as client:
            # 用task，用完就關閉對話
            await client.post(url, params=params)
            # 把內容傳送給fastapi，理應來說會很迅速地收到結果
            # 語法上(url: 要傳送到哪，params = 我們要送給fastapi的內容)params 在上方我們設定了很多START_V...


def pv_chart() -> rx.Component:
    """
    設定pv_chart()函數，作為rx物件
    """
    return rx.recharts.line_chart(
        rx.recharts.line(
            data_key="voltage",
            stroke="#8884d8",
            is_animation_active=False,  # 很重要
            # 如果這個打開，資料會持續從一開始推送出來，讓視覺上看起來很詭異
        ),
        rx.recharts.x_axis(
            data_key="time_second",
            label="Time (s)",
            type_="number",  # 明確指定為數值型軸，domain 才會生效
            domain=[0, 10],
        ),
        rx.recharts.y_axis(data_key="voltage", label="Voltage (V)"),
        data=State.pv_chart_data,
        width=600,
        height=300,
        margin={"left": 30, "right": 20, "top": 10, "bottom": 10},
    )


def jv_chart() -> rx.Component:
    return rx.recharts.line_chart(
        rx.recharts.line(data_key="current", stroke="#82ca9d"),
        rx.recharts.x_axis(data_key="voltage", label="Voltage (V)"),
        rx.recharts.y_axis(label="Current (A)"),
        data=State.jv_chart_data,
        width=600,
        height=300,
        margin={"left": 30, "right": 20, "top": 10, "bottom": 10},
    )


# 將兩種plot的繪圖都設定成def，當要進行繪圖的時候，直接召喚函數出來使用
# 如果是把plot物件寫死，reflex在更新畫面，會判斷同個物件不可以再次使用


def index() -> rx.Component:
    # 主函數：也就是rx主畫面的模樣
    # -----------------------------建立測量的基本選單與條件---------------------------
    # fmt: off
    measurement_selection = rx.match(  # rx.match 是rx內的條件判別函式
        State.measurement_type,
    # -----jv條件-----
        ("jv",rx.vstack(
            rx.text("Keithley JV sweep ONLY"),
            # rx.input(
            #     placeholder="START_V",
            #     # 預設的使用者輸入框：顯示START_V
            #     value=State.start_v.to_string(),
            #     # 真正的輸入框，也會在使用者輸入後，顯示輸入的內容
            #     on_change=State.set_start_v,
            #     # 當Vars被改變，將Vars傳送給指定Event handlers，此處會傳給set_start_v
            #     #這邊是基礎輸入框，沒有使用到labeled_input，會要打很多行
            # ), #rx.input 的結尾
            labeled_input("Start voltage (V)",State.start_v.to_string(),State.set_start_v),
            labeled_input("Stop voltage (V)",State.stop_v.to_string(),State.set_stop_v),
            labeled_input("Step voltage (V)",State.step_v.to_string(),State.set_step_v),
            labeled_input("Compliance current (A)",State.compliance_a.to_string(),State.set_compliance_a),
            labeled_input("Source delay (s)",State.source_delay.to_string(),State.set_source_delay),
                        ),  # rx.vstack的結尾
        ),  # jv條件的結尾
    # -----pv條件-----
        ("pv",rx.vstack(
                rx.text("6211 daq PV measurement ONLY"),
                labeled_input("Sample rate (Hz)",State.sample_rate.to_string(),State.set_sample_rate),
                        ),  # rx.vstack的結尾
        ),  # pv條件的結尾
        # -----jv_pv_sync條件-----
        ("jv_pv_sync",rx.vstack(
                rx.text("Keithley JV sweep + 6211 daq PV measurement"),
                labeled_input("Start voltage (V)",State.start_v.to_string(),State.set_start_v),
                labeled_input("Stop voltage (V)",State.stop_v.to_string(),State.set_stop_v),
                labeled_input("Step voltage (V)",State.step_v.to_string(),State.set_step_v),
                labeled_input("Compliance current (A)",State.compliance_a.to_string(),State.set_compliance_a),
                labeled_input("Source delay (s)",State.source_delay.to_string(),State.set_source_delay),
                labeled_input("Sample rate (Hz)",State.sample_rate.to_string(),State.set_sample_rate),
                                ),  # 內部rx.vstack的結尾
        ),  # jv_pv_sync條件的結尾
    )  # rx.match，條件函式的結尾
    # fmt: on
    chart_display = rx.match(
        # chart是吃數據內容產生的，如果數據沒有消失，圖片就會持續保留
        # 因此設定在status=running會先清空一次數據
        State.measurement_type,
        ("jv", jv_chart()),
        ("pv", pv_chart()),
        ("jv_pv_sync", rx.vstack(jv_chart(), pv_chart())),
        rx.text("未知的量測方式"),
    )
    # 設定chart_display的條件，當選擇不同條件時，會顯示不同的圖
    return rx.container(
        # 整體網頁的基礎設定
        # return 會把index()的內容回傳給rx，rx就會知道要顯示甚麼
        rx.heading("Keithley Measurement"),
        rx.text("Select a measurement type:"),
        # ----------------------------建立下拉選單---------------------------
        rx.hstack(
            rx.vstack(  # 垂直排列的子元件內容
                rx.select(  # 下拉選單內容
                    ["jv", "pv", "jv_pv_sync"],  # 下拉選單的內容有什麼
                    value=State.measurement_type,  # 這行顯示下拉選單目前是甚麼
                    # measurement_type 預設是jv，所以下拉選單預設是jv
                    on_change=State.set_measurement_type,
                    # 當Vars被改變，將Vars傳送給指定Event handlers，此處會傳給set_measurement_type
                ),
                measurement_selection,
                rx.button("開始量測", on_click=State.start_measurement),
                # on_click 表示當按鈕被點擊時，會呼叫State.start_measurement函數
            ),
            chart_display,
            align="start",
            spacing="8",
            width="100%",
        ),  # hstack的結尾
        on_mount=State.listen_status,
    )  # Container的結尾
    # 這邊有個關鍵：on_mount是關鍵字引數，需要放在位置引數後放。上方的內容都是位置引數
    # on_mount 是設定這個container的屬性，當發生改變時，會呼叫State.listen_status函數


app = rx.App()
app.add_page(index)
