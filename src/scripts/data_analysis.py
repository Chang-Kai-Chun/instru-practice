import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import cmcrameri.cm as cmc


PV_FILE = "pv_triggered_1.csv"
JV_FILE = "Keithley_JV_sweep_1.csv"


def jv_plot(filename: str = JV_FILE):
    df = pd.read_csv(filename)
    # 先預設檔案名稱為 JV_FILE，從其他地方招喚此函式時，會從該處傳入filename

    fig, ax = plt.subplots(figsize=(8, 5))
    ax.plot(
        df["Voltage (V)"],
        df["Current (A)"].abs(),
        color=cmc.batlow(0.3),
        lw=1.2,
        marker="o",
        ms=3,
        label="JV-sweep",
    )

    ax.set_title("J-V Sweep", fontsize=14)
    ax.set_xlabel("Voltage (V)")
    ax.set_ylabel("|Current| (A)")
    ax.set_xlim(-0.7, 3.2)
    ax.set_yscale("log")
    ax.set_ylim(1e-11, 1e-2)
    ax.grid(True, which="both", linestyle="--", alpha=0.4)
    ax.legend(frameon=False)

    fig.tight_layout()
    fig.savefig(f"{filename}.png", dpi=300)
    plt.close()  # 直接存圖片，不需要開啟圖片


def pv_plot(filename: str = PV_FILE):
    df = pd.read_csv(filename)  # 先建立dataframe，萬物之根源
    # 這裡預設檔案名稱為 PV_FILE，從其他地方招喚此函式時，會從該處傳入filename

    fig, ax = plt.subplots(figsize=(8, 5))
    ax.plot(
        df["Time (s)"],
        df["Voltage (V)"],
        color=cmc.batlow(0.3),
        lw=1.2,
        label="PV triggered",
    )

    ax.set_title("Photovoltage vs Time", fontsize=14)
    ax.set_xlabel("Time (s)")
    ax.set_ylabel("Voltage (V)")
    ax.set_xlim(-1, 10)  # x 軸範圍
    ax.set_ylim(0.05, 0.4)  # y 軸範圍
    ax.set_xscale("linear")  # 對數座標（也可 "linear"）
    ax.set_yscale("linear")  # 暗電流常用 y 軸取對數
    ax.grid(True, linestyle="--", alpha=0.4)
    ax.legend(frameon=False)

    fig.tight_layout()
    fig.savefig(f"{filename}.png", dpi=300)
    plt.close()  # 直接存圖片，不需要開啟圖片
