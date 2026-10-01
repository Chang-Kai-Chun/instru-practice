"""
Pi Pico 控制模組（目前是假硬體 stub）。

之後真的接上 Pico 時，預計會透過 USB 序列埠（pyserial）跟它溝通，
例如開一個 serial.Serial(PICO_PORT, BAUD_RATE) 連線，送一個指令字串
（例如 b"PLAY\n"）告訴 Pico 開始用喇叭播放聲音。

現在硬體還沒接上，所以 start_pi_pico() 先用 print + asyncio.sleep
模擬「送出指令」跟「Pico 播放需要一段時間」這兩件事，
之後真的接上 Pico，只需要把 start_pi_pico() 函式內部換成
真正的 pyserial 呼叫，呼叫端（async_led.py）完全不用改。
"""

import asyncio


PICO_PORT = "COM3"  # 之後接上 Pico 時，實際的 USB 序列埠名稱
PICO_BAUD_RATE = 115200  # 序列埠通訊速率，跟 Pico 端程式要設定一致
PLAY_DURATION = 3  # 秒，模擬 Pico 播放聲音需要的時間


def _send_play_command_blocking():
    """
    假裝透過序列埠送出「開始播放」指令。
    之後接上真的 Pico，這裡會換成類似：
        with serial.Serial(PICO_PORT, PICO_BAUD_RATE, timeout=1) as ser:
            ser.write(b"PLAY\\n")
    這是一般(同步、會卡住)函式，所以呼叫端一樣要用 asyncio.to_thread() 包起來。
    """
    print(f"[模擬] 透過 {PICO_PORT} 送出 PLAY 指令給 Pico...")


async def start_pi_pico():
    """觸發 Pico 播放聲音，等待播放完成後才返回"""
    print("開始觸發 Pi Pico 喇叭...")
    await asyncio.to_thread(_send_play_command_blocking)

    # 模擬「Pico 正在播放聲音」需要的時間，
    # 之後接上真的硬體，這裡可能改成等待 Pico 回傳「播放完成」的訊息，
    # 而不是單純用固定秒數 sleep。
    await asyncio.sleep(PLAY_DURATION)

    print(f"Pi Pico 播放結束（模擬維持了 {PLAY_DURATION} 秒）")
