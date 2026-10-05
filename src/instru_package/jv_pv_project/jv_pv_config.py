from instru_package import only_led_shining_config

# For Keithley
KITTY_RESOURCE = "GPIB0::24::INSTR"
KITTY_TIMEOUT_MS = 90000
START_V = -0.5  # 起始電壓
STOP_V = 3  # 終止電壓
STEP_V = 0.1  # 步進電壓
COMPLIANCE_A = 1e-1  # 電流保護值
SOURCE_DELAY = 0.05  # 每個電壓點維持多久才(ms)

# For 6211
device_name = only_led_shining_config.device_name  # 儀器名稱，請依實際情況修改
SAMPLE_RATE = 1000  # 6211 AI 取樣率，單位 Hz
AI_CHANNEL = "ai1"  # 6211 AI 通道
DURATION_SECONDS = 10
