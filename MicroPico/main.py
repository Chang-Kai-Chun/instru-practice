import sys
from machine import Pin, PWM
import time

buzzer = PWM(Pin(18))  # 板載喇叭固定接在 GP18

while True:
    cmd = sys.stdin.readline().strip()  
    # 等電腦透過 USB 序列埠送指令過來
    if cmd == "PLAY":
        buzzer.freq(500)  # 設定音頻 500Hz
        buzzer.duty_u16(3000)  # 開始發聲（音量大小）
        time.sleep(1)  # 響 1 秒
        buzzer.duty_u16(0)  # 關閉聲音
        print("DONE")  # 回報電腦：播放完成
