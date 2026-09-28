import serial
import time

ser = serial.Serial("COM8", 115200, timeout=2)  # COM3 換成您實際查到的編號
time.sleep(2)  # 給 Pico 一點時間穩定，剛插上/重開機時序列埠不會馬上就緒
ser.write(b"PLAY\n")
print(ser.readline())
ser.close()
