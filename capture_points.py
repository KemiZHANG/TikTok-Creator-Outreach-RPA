import time
from pathlib import Path

import keyboard
import pyautogui


LOG_FILE = Path(__file__).resolve().parent / "logs" / "captured_points.txt"


def main() -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    print("TikTok_BD_Auto 坐标采集工具")
    print("按 F8 输出当前鼠标坐标并追加保存到 logs/captured_points.txt")
    print("按 ESC 退出")
    print("-" * 60)

    last_f8_state = False
    try:
        while True:
            esc_pressed = keyboard.is_pressed("esc")
            if esc_pressed:
                print("检测到 ESC，已退出。")
                break

            f8_pressed = keyboard.is_pressed("f8")
            if f8_pressed and not last_f8_state:
                x, y = pyautogui.position()
                line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} -> x={x}, y={y}"
                print(line)
                with LOG_FILE.open("a", encoding="utf-8") as file:
                    file.write(line + "\n")
            last_f8_state = f8_pressed
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("已通过 Ctrl+C 退出。")
    except Exception as exc:
        print(f"运行异常: {exc}")
        print("如果 keyboard 无法监听全局按键，请尝试以管理员身份运行 PowerShell。")


if __name__ == "__main__":
    main()
