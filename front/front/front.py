import reflex as rx
import httpx

FASTAPI_URL = "http://localhost:8000"


def labeled_input(label: str, value, on_change) -> rx.Component:
    """
    建立一個有標籤的輸入框函式，未來不需要每個都打得很長
    """
    return rx.vstack(
        rx.text(label, size="1", color="gray"),
        rx.input(
            value=value,
            on_change=on_change,
        ),
        spacing="1",
    )


class State(rx.State):
    # 先定義出一個類別為：state
    measurement_type: str = "jv"
    # 內容有一個measurement_type，類型是str，就是我們接下來要選的，先預設顯示為jv
    start_v: float = -0.5
    stop_v: float = 3.0
    step_v: float = 0.01
    compliance_a: float = 0.01
    sample_rate: float = 1000.0
    source_delay: float = 0.005
    status: str = "idle"

    @rx.event
    # 裝飾器，在rx，這個是用來讓此函數可以被rx呼叫的裝飾器
    def set_measurement_type(self, value: str):
        # set_measurement_type 作為rx的後端，會把改變的變數傳出去
        self.measurement_type = value
        # 設定本函數為set_measurement_type，rx呼叫時，會把value傳進來
        # 當本函數收到value例如 value="pv"，就會把measurement_type改成"pv"
        # 下方index()就會知道現在該顯示甚麼

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
        """
        self.status = "running"

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
            params = {"SAMPLE_RATE": self.sample_rate}
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
            await client.post(url, params=params)


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

    return rx.container(
        # 整體網頁的基礎設定
        # return 會把index()的內容回傳給rx，rx就會知道要顯示甚麼
        rx.heading("Keithley Measurement"),
        rx.text("Select a measurement type:"),
        # ----------------------------建立下拉選單---------------------------
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
        ),  # 整體網頁的vstack的結尾
    )  # Container的結尾


app = rx.App()
app.add_page(index)
