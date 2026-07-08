"""LED 补光 PWM 调光 v2: GPIO4_A0 (Linux GPIO128), 经光耦→PWM板→LED。
高精度软件 PWM 1000Hz, 支持平滑过渡, 防闪烁。duty 0-85%。"""
import os, time, threading

GPIO_LED = 128          # GPIO4_A0 = 4×32 + 0×8 + 0
PWM_FREQ  = 1000        # Hz, 恒流模块推荐1000Hz
MAX_DUTY  = 85.0        # 最大占空比85%，超过线性度恶化
PWM_PERIOD = 1.0 / PWM_FREQ
MIN_SLEEP  = 0.0001     # 100µs 最小睡眠, 低于此用忙等 (1000Hz需更快)

BASE = "/sys/class/gpio"
PATH = f"{BASE}/gpio{GPIO_LED}"
ACTIVE = 0   # 低电平有效 (光耦→PWM板 3.3V控制)
IDLE   = 1

_running = False
_target = 0.0         # 目标亮度 0-100
_current = 0.0        # 当前亮度 (平滑跟踪)
_thread = None
_lock = threading.Lock()
_exported = False


def _write(path, val):
    with open(path, "w") as f:
        f.write(str(val))


def _ensure_exported():
    global _exported
    if _exported:
        return
    if not os.path.isdir(PATH):
        _write(f"{BASE}/export", GPIO_LED)
        time.sleep(0.05)
    _write(f"{PATH}/direction", "out")
    _write(f"{PATH}/value", IDLE)
    _exported = True


def _pwm_loop():
    """高精度软件 PWM: perf_counter 计时 + 忙等微秒级精度"""
    global _current, _running
    while _running:
        with _lock:
            cur = _current
        if cur <= 0:
            _write(f"{PATH}/value", IDLE)
            time.sleep(0.02)
            continue
        if cur >= MAX_DUTY:
            _write(f"{PATH}/value", ACTIVE)
            time.sleep(0.02)
            continue

        on_ns  = PWM_PERIOD * cur / 100.0
        off_ns = PWM_PERIOD - on_ns

        t0 = time.perf_counter()

        # ON phase
        _write(f"{PATH}/value", ACTIVE)
        while True:
            elapsed = time.perf_counter() - t0
            remain = on_ns - elapsed
            if remain <= 0:
                break
            if remain > MIN_SLEEP:
                time.sleep(min(remain / 2, 0.001))
            # else: busy-wait

        # OFF phase
        _write(f"{PATH}/value", IDLE)
        t1 = time.perf_counter()
        while True:
            elapsed = time.perf_counter() - t1
            remain = off_ns - elapsed
            if remain <= 0:
                break
            if remain > MIN_SLEEP:
                time.sleep(min(remain / 2, 0.001))


def _ramp_thread(target):
    """平滑过渡线程: 从当前位置逐步调到目标, 避免跳跃闪烁"""
    global _current, _running
    start = _current
    steps = max(8, int(abs(target - start) / 2))  # 每步约2%, 最少8步
    step_ms = max(0.015, 0.4 / steps)             # 总时长~400ms, 最少15ms/步

    for i in range(1, steps + 1):
        if not _running:
            break
        pct = start + (target - start) * i / steps
        with _lock:
            _current = pct
        time.sleep(step_ms)
    with _lock:
        _current = target


def set_brightness(pct, smooth=True):
    """设置亮度 0-85%, smooth=True 平滑过渡防闪烁"""
    global _running, _target, _current, _thread
    pct = max(0.0, min(MAX_DUTY, float(pct)))

    with _lock:
        if abs(pct - _target) < 0.3 and _running:
            return  # 没变化, 跳过
        _target = pct

    if pct <= 0 and _current <= 0:
        _stop_pwm()
        return

    if not _running:
        _ensure_exported()
        _running = True
        _thread = threading.Thread(target=_pwm_loop, daemon=True)
        _thread.start()

    if smooth and abs(pct - _current) > 1:
        threading.Thread(target=_ramp_thread, args=(pct,), daemon=True).start()
    else:
        with _lock:
            _current = pct


def _stop_pwm():
    global _running, _target, _current, _exported, _thread
    _running = False
    _target = 0.0
    with _lock:
        _current = 0.0
    try:
        _write(f"{PATH}/value", IDLE)
    except Exception:
        pass


def status():
    with _lock:
        return {"gpio": GPIO_LED, "target": _target, "current": round(_current, 1),
                "freq_hz": PWM_FREQ, "running": _running}


def cleanup():
    _stop_pwm()
    global _exported
    if _exported:
        try:
            _write(f"{BASE}/unexport", GPIO_LED)
        except Exception:
            pass
        _exported = False


if __name__ == "__main__":
    import argparse, json
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", nargs="?", default="status",
                    choices=["on", "off", "set", "fade", "status", "blink"])
    ap.add_argument("value", nargs="?", type=float, default=MAX_DUTY)
    ap.add_argument("--ms", type=int, default=800)
    args = ap.parse_args()

    if args.cmd == "on":
        set_brightness(MAX_DUTY)
    elif args.cmd == "off":
        set_brightness(0)
    elif args.cmd == "set":
        set_brightness(args.value)
    elif args.cmd == "fade":
        set_brightness(0, smooth=False)
        time.sleep(0.1)
        set_brightness(args.value, smooth=True)
    elif args.cmd == "blink":
        print("LED 1Hz 闪烁 x3")
        for i in range(3):
            set_brightness(MAX_DUTY, smooth=False)
            time.sleep(0.5)
            set_brightness(0, smooth=False)
            time.sleep(0.5)
        print("完成")
    else:
        print(json.dumps(status(), ensure_ascii=False))

    if args.cmd != "status":
        time.sleep(0.5)  # 等 PWM 稳定
    cleanup()
