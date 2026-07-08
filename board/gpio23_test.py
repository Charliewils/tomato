"""GPIO23 (丝印) = GPIO4_A1 = Linux GPIO129, 低电平有效 1Hz 测试信号"""
import time, os, sys

GPIO = 129   # GPIO4_A1: 4×32 + 0×8 + 1 = 129
BASE = "/sys/class/gpio"
PATH = f"{BASE}/gpio{GPIO}"


def _write(path, val):
    with open(path, "w") as f:
        f.write(str(val))


def main():
    if not os.path.isdir(PATH):
        _write(f"{BASE}/export", GPIO)
        time.sleep(0.1)

    _write(f"{PATH}/direction", "out")
    _write(f"{PATH}/value", 1)   # 初始高电平（非激活，继电器断开）

    print(f"GPIO{GPIO} (GPIO4_A1, 板子丝印 GPIO23) 1Hz 低电平有效测试，Ctrl-C 停止")
    try:
        while True:
            _write(f"{PATH}/value", 0)   # 低电平=激活
            sys.stdout.write("\r[激活] 0  "); sys.stdout.flush()
            time.sleep(0.5)
            _write(f"{PATH}/value", 1)   # 高电平=空闲
            sys.stdout.write("\r[空闲] 1  "); sys.stdout.flush()
            time.sleep(0.5)
    except KeyboardInterrupt:
        _write(f"{PATH}/value", 1)
        print(f"\n已停止，GPIO{GPIO} 置高电平(非激活)")


if __name__ == "__main__":
    main()
