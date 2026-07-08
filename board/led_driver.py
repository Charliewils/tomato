import os, time, json, sys, argparse

# 恒压转恒流 LED 模块 EN/PWM 口：硬件 PWM 调光，占空比=亮度
# RV1126B sysfs PWM，period/duty 单位 ns；下面两行按原理图填实际通道
PWMCHIP = 0          # /sys/class/pwm/pwmchipN 的 N
CHANNEL = 0          # 该 chip 下的通道号
FREQ_HZ = 1000       # 1kHz 无可见闪烁，多数恒流模块 PWM 口可接受 0.1~20kHz
MAX_DUTY_PCT = 85.0  # 最大占空比85%，恒流模块EN口超过85%时线性度恶化
ACTIVE_LOW = False   # True=占空比越大越暗（EN 反逻辑模块）

PERIOD_NS = int(1e9 / FREQ_HZ)
_BASE = "/sys/class/pwm/pwmchip{}".format(PWMCHIP)
_PWM = "{}/pwm{}".format(_BASE, CHANNEL)


def _write(path, val):
    with open(path, "w") as f:
        f.write(str(val))


def _exported():
    return os.path.isdir(_PWM)


class LEDDriver:
    def __init__(self):
        self._enabled = False
        self._duty_pct = 0.0
        self._setup()

    def _setup(self):
        if not os.path.isdir(_BASE):
            raise RuntimeError("无 PWM 控制器 {}，检查 PWMCHIP 或 dtb 引脚复用".format(_BASE))
        if not _exported():
            _write("{}/export".format(_BASE), CHANNEL)
            for _ in range(50):                       # export 后节点出现有延迟
                if _exported():
                    break
                time.sleep(0.01)
        _write("{}/period".format(_PWM), PERIOD_NS)
        _write("{}/polarity".format(_PWM), "inversed" if ACTIVE_LOW else "normal")
        self._apply(0.0)

    def _apply(self, pct):
        pct = max(0.0, min(MAX_DUTY_PCT, pct))
        duty = int(PERIOD_NS * pct / 100.0)
        _write("{}/duty_cycle".format(_PWM), duty)
        self._duty_pct = pct

    def set_brightness(self, pct):
        self._apply(pct)
        if not self._enabled:
            self.on()

    def on(self):
        _write("{}/enable".format(_PWM), 1)
        self._enabled = True

    def off(self):
        _write("{}/enable".format(_PWM), 0)
        self._enabled = False

    def fade(self, target_pct, ms=500, steps=25):
        start = self._duty_pct
        if not self._enabled:
            self.on()
        for i in range(1, steps + 1):
            self._apply(start + (target_pct - start) * i / steps)
            time.sleep(ms / 1000.0 / steps)

    def status(self):
        return {"enabled": self._enabled, "brightness": round(self._duty_pct, 1),
                "freq_hz": FREQ_HZ, "active_low": ACTIVE_LOW,
                "pwmchip": PWMCHIP, "channel": CHANNEL}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["on", "off", "set", "fade", "status"])
    ap.add_argument("value", nargs="?", type=float, default=MAX_DUTY_PCT)
    a = ap.parse_args()
    d = LEDDriver()
    if a.cmd == "on":
        d.set_brightness(MAX_DUTY_PCT)
    elif a.cmd == "off":
        d.off()
    elif a.cmd == "set":
        d.set_brightness(a.value)
    elif a.cmd == "fade":
        d.fade(a.value)
    print(json.dumps(d.status(), ensure_ascii=False))
