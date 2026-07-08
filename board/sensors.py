import fcntl, os, time, json, sys, ctypes, argparse

import led_dimmer

I2C_RDWR = 0x0707
I2C_SLAVE, I2C_SLAVE_FORCE = 0x0703, 0x0706

# 各传感器直连各自 I2C 总线
BUS_VEML = "/dev/i2c-4"
BUS_SOIL = "/dev/i2c-3"
BUS_SCD  = "/dev/i2c-4"

# 自动补光参数
LUX_TARGET = 1500
LUX_HYST = 300
LIGHT_MIN_PCT = 15
STEP_PCT = 8

# 电容式土壤探头标定：干(空气)→0%，湿(泡水)→100%
SOIL_DRY_V = 2.772
SOIL_WET_V = 1.540


class _i2c_msg(ctypes.Structure):
    _fields_ = [("addr", ctypes.c_uint16), ("flags", ctypes.c_uint16),
                ("len", ctypes.c_uint16), ("buf", ctypes.c_void_p)]


class _i2c_rdwr(ctypes.Structure):
    _fields_ = [("msgs", ctypes.c_void_p), ("nmsgs", ctypes.c_uint32)]


def rdwr_read_word(fd, addr, reg):
    wbuf = (ctypes.c_uint8 * 1)(reg & 0xFF)
    rbuf = (ctypes.c_uint8 * 2)()
    msgs = (_i2c_msg * 2)(
        _i2c_msg(addr, 0, 1, ctypes.cast(wbuf, ctypes.c_void_p)),
        _i2c_msg(addr, 1, 2, ctypes.cast(rbuf, ctypes.c_void_p)))
    req = _i2c_rdwr(ctypes.cast(msgs, ctypes.c_void_p), 2)
    fcntl.ioctl(fd, I2C_RDWR, req)
    return rbuf[0] | (rbuf[1] << 8)


def rdwr_read_bytes(fd, addr, reg, n):
    wbuf = (ctypes.c_uint8 * 1)(reg & 0xFF)
    rbuf = (ctypes.c_uint8 * n)()
    msgs = (_i2c_msg * 2)(
        _i2c_msg(addr, 0, 1, ctypes.cast(wbuf, ctypes.c_void_p)),
        _i2c_msg(addr, 1, n, ctypes.cast(rbuf, ctypes.c_void_p)))
    req = _i2c_rdwr(ctypes.cast(msgs, ctypes.c_void_p), 2)
    fcntl.ioctl(fd, I2C_RDWR, req)
    return list(rbuf)


def _open_addr(bus, addr):
    fd = os.open(bus, os.O_RDWR)
    try:
        fcntl.ioctl(fd, I2C_SLAVE, addr)
    except OSError:
        fcntl.ioctl(fd, I2C_SLAVE_FORCE, addr)
    return fd


def soil_pct(v):
    p = (SOIL_DRY_V - v) / (SOIL_DRY_V - SOIL_WET_V) * 100
    return round(max(0.0, min(100.0, p)), 1)


def _crc8(b0, b1):
    crc = 0xFF
    for b in (b0, b1):
        crc ^= b
        for _ in range(8):
            crc = ((crc << 1) ^ 0x31) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
    return crc


class VEML7700:
    ADDR = 0x10
    RANGES = [(0.125, 25, 1.8432), (0.125, 100, 0.4608),
              (1, 100, 0.0576), (1, 800, 0.0072), (2, 800, 0.0036)]
    GB = {1: 0b00, 2: 0b01, 0.125: 0b10, 0.25: 0b11}
    ITB = {25: 0b1000, 50: 0b1100, 100: 0b0000, 200: 0b0001, 400: 0b0010, 800: 0b0011}

    def __init__(self, bus=BUS_VEML):
        self.fd = _open_addr(bus, self.ADDR)

    def _cfg(self, gain, it):
        conf = (self.GB[gain] << 11) | (self.ITB[it] << 6)
        os.write(self.fd, bytes([0x00, (conf | 1) & 0xFF, (conf >> 8) & 0xFF]))
        time.sleep(0.05)
        os.write(self.fd, bytes([0x00, conf & 0xFF, (conf >> 8) & 0xFF]))
        time.sleep(it / 1000.0 * 2.5 + 0.05)

    def _rd(self, reg):
        return rdwr_read_word(self.fd, self.ADDR, reg)

    def read_lux(self):
        for i, (g, it, res) in enumerate(self.RANGES):
            self._cfg(g, it)
            raw = self._rd(0x04)
            if raw >= 60000 and i > 0:
                g0, it0, res0 = self.RANGES[i - 1]
                self._cfg(g0, it0); raw = self._rd(0x04)
                return round(raw * res0, 1), raw
            if raw >= 100 or i == len(self.RANGES) - 1:
                return round(raw * res, 1), raw
        return round(raw * res, 1), raw

    def close(self):
        os.close(self.fd)


class ADS1115:
    ADDR = 0x48

    def __init__(self, bus=BUS_SOIL, ain=0):
        self.ain = ain
        self.available = False
        self.fd = -1
        try:
            self.fd = _open_addr(bus, self.ADDR)
            rdwr_read_bytes(self.fd, self.ADDR, 0x01, 2)
            self.available = True
        except OSError:
            if self.fd >= 0:
                os.close(self.fd); self.fd = -1

    def read_voltage(self):
        cfg = ((1 << 15) | ((0b100 + self.ain) << 12) | (0b001 << 9) |
               (1 << 8) | (0b100 << 5) | 0b11)
        os.write(self.fd, bytes([0x01, (cfg >> 8) & 0xFF, cfg & 0xFF]))
        time.sleep(0.01)
        b = rdwr_read_bytes(self.fd, self.ADDR, 0x00, 2)
        raw = (b[0] << 8) | b[1]
        if raw >= 0x8000:
            raw -= 0x10000
        return raw * 4.096 / 32768

    def close(self):
        if self.fd >= 0:
            os.close(self.fd)


class SCD41:
    ADDR = 0x62

    def __init__(self, bus=BUS_SCD):
        self.available = False
        self.fd = -1
        try:
            self.fd = _open_addr(bus, self.ADDR)
            self._cmd(0x3F86, 0.5)
            self._cmd(0x21B1)
            self.available = True
        except OSError:
            if self.fd >= 0:
                os.close(self.fd); self.fd = -1

    def _cmd(self, c, delay=0):
        os.write(self.fd, bytes([c >> 8, c & 0xFF]))
        if delay:
            time.sleep(delay)

    def _words(self, cmd, n, wait):
        self._cmd(cmd); time.sleep(wait)
        raw = os.read(self.fd, n * 3)
        out = []
        for i in range(n):
            b0, b1, c = raw[i * 3:i * 3 + 3]
            if _crc8(b0, b1) != c:
                raise IOError("scd41 crc")
            out.append((b0 << 8) | b1)
        return out

    def ready(self):
        return (self._words(0xE4B8, 1, 0.002)[0] & 0x07FF) != 0

    def read(self):
        co2, t, rh = self._words(0xEC05, 3, 0.002)
        return co2, round(-45 + 175 * t / 65535, 1), round(100 * rh / 65535, 1)

    def stop(self):
        if self.available:
            self._cmd(0x3F86, 0.5)

    def close(self):
        if self.fd >= 0:
            os.close(self.fd)


class GrowLight:
    def __init__(self, target=LUX_TARGET):
        self.target = target
        self._pct = 0.0
        self.err = None

    def _set(self, pct):
        pct = max(0.0, min(85.0, pct))
        try:
            led_dimmer.set_brightness(pct)
        except Exception as e:
            self.err = str(e)
        self._pct = pct

    def update(self, lux):
        if lux is None:
            return {"light": None, "err_light": self.err or "no_lux"}
        if lux >= self.target + LUX_HYST:
            tgt = 0.0
        else:
            tgt = min(85.0, max(0.0, self.target - lux) / self.target * 85.0)
            if 0 < tgt < LIGHT_MIN_PCT:
                tgt = LIGHT_MIN_PCT
        nxt = self._pct + max(-STEP_PCT, min(STEP_PCT, tgt - self._pct))
        try:
            self._set(nxt)
        except Exception as e:
            self.err = str(e)
            return {"light": None, "err_light": str(e)}
        return {"light": round(self._pct, 1), "light_target_lux": self.target}

    def off(self):
        try:
            led_dimmer.set_brightness(0)
        except Exception:
            pass


def read_all(veml, scd, soil, wait_scd=True):
    out = {"ts": int(time.time())}

    lux, raw = veml.read_lux()
    out["lux"], out["lux_raw"] = lux, raw

    if soil.available:
        v = soil.read_voltage()
        out["soil_v"], out["soil"] = round(v, 3), soil_pct(v)
    else:
        out["soil_v"], out["soil"] = None, None

    if scd.available:
        if wait_scd:
            for _ in range(12):
                if scd.ready():
                    break
                time.sleep(0.5)
        co2, temp, rh = scd.read()
        out["co2"], out["temp"], out["rh"] = co2, temp, rh
    else:
        out["co2"], out["temp"], out["rh"] = None, None, None

    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--daemon", action="store_true")
    ap.add_argument("--interval", type=int, default=5)
    ap.add_argument("--out", default="/userdata/sensors.json")
    ap.add_argument("--no-light", action="store_true")
    ap.add_argument("--lux-target", type=int, default=LUX_TARGET)
    args = ap.parse_args()

    veml, scd, soil = VEML7700(), SCD41(), ADS1115()
    grow = None if args.no_light else GrowLight(args.lux_target)
    try:
        if not args.daemon:
            d = read_all(veml, scd, soil)
            if grow:
                d.update(grow.update(d["lux"]))
            print(json.dumps(d, ensure_ascii=False))
        else:
            while True:
                d = read_all(veml, scd, soil, wait_scd=False)
                if grow:
                    d.update(grow.update(d["lux"]))
                tmp = args.out + ".tmp"
                with open(tmp, "w") as f:
                    json.dump(d, f, ensure_ascii=False)
                os.replace(tmp, args.out)
                print(json.dumps(d, ensure_ascii=False), flush=True)
                time.sleep(args.interval)
    finally:
        if grow:
            grow.off()
        scd.stop(); veml.close(); scd.close(); soil.close()


if __name__ == "__main__":
    main()
