import os


def get_next_filename(prefix="test", ext="csv"):
    i = 0
    while True:
        filename = f"{prefix}_{i}.{ext}"
        if not os.path.exists(filename):
            return filename

        i += 1
    print(f"已存在檔案 {filename}，將嘗試下一個檔名...")


get_next_filename(prefix="test")
