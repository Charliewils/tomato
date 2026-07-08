"""执行器控制 v2: 基于文献的病害感知温室气候管理。

文献来源见文件末尾 REFERENCES。

控制策略:
  1. 从 plants.json 读取各株病害, 判定温室病害态势
  2. 根据病害类型选择文献推荐的目标温湿度/VPD/光照范围
  3. 风扇控制温湿度, 水泵控制土壤湿度, LED控制补光
  4. 冷却/最短运行/最长运行保护
  5. 手动覆盖支持(LLM Agent 调用)
"""
import os, time, json, math, argparse, threading
from datetime import datetime

# ══════════════════════════════════════════════════════
# GPIO 定义
# ══════════════════════════════════════════════════════
GPIO_FAN  = 129   # 丝印 GPIO23, GPIO4_A1, 继电器→风扇
GPIO_PUMP = 111   # 丝印 GPIO3_B7_D, 继电器→水泵
GPIO_LED  = 128   # 丝印 GPIO4_A0, 软件PWM→光耦→PWM板→LED
ACTIVE = 0         # 低电平有效
IDLE   = 1

# ══════════════════════════════════════════════════════
# 通用安全参数
# ══════════════════════════════════════════════════════
FAN_MIN_RUN    = 60     # 风扇最短运行秒(防短促抖动)
FAN_COOLDOWN   = 120    # 风扇关后冷却秒(防频繁启停)
FAN_MIN_OFF    = 120    # 风扇最短关闭秒
PUMP_MAX_RUN   = 30     # 水泵单次最长灌溉秒
PUMP_COOLDOWN  = 600    # 灌溉后冷却秒(10分钟等水渗透)
PUMP_MIN_ON    = 10     # 水泵最短运行秒

# ══════════════════════════════════════════════════════
# LED 补光参数 [R11-R16]
# ══════════════════════════════════════════════════════
# PPFD(lux)换算: 白光LED ≈ 1klux→15µmol/m²/s, 日光≈1klux→18µmol/m²/s
# 取保守值 1klux→14µmol/m²/s
LUX_TO_PPFD = 14.0       # µmol/m²/s per klux

# DLI 目标 [R11]: 番茄结果期 20-30 mol/m²/day, 取 22
DLI_TARGET = 22           # mol/m²/day
PHOTOPERIOD = 16          # 小时/天 [R11]: 16-18h, 取16h防光周期伤害
# 折算为平均 PPFD: 22e6 µmol / (16*3600)s ≈ 382 µmol/m²/s → 27 klux
LUX_TARGET_DAY = 27000    # lux, 日间目标总光照(≈386 µmol/m²/s)

# 补光触发: 环境 lux < 此值才开灯, 避免白天自然光足够时浪费
LUX_SUPPLEMENT_ON  = 15000  # [R12]: 地中海温室阈值为200 µmol/m²/s≈14klux, 取15klux
LUX_SUPPLEMENT_OFF = 25000  # 环境光超过此值关灯

# 补光时段 [R11]: 6:00-22:00 (16h 光照窗口)
LIGHT_ON_HOUR  = 6
LIGHT_OFF_HOUR = 22

# LED 调光参数
LED_MIN_PCT  = 5     # 最低亮度%, 低于此直接关
LED_MAX_PCT  = 100
LED_STEP_PCT = 10    # 每周期最大调整幅度
LED_HYST     = 2000  # lux 滞后带

# 病害模式调整 [R14,R15]: 蓝光抑制灰霉/早疫, 强光增强抗病性
# 真菌病害 → 增强光照(提升植物防御酶活性)
# 正常 → 标准 DLI
DISEASE_LIGHT_BOOST = {
    "early_blight": 1.15,
    "late_blight": 1.15,
    "leaf_mold": 1.15,
    "septoria": 1.10,
    "gray_mold": 1.20,      # [R14] 蓝光/强光抑制 Botrytis
    "bacterial_spot": 1.10,
    "spider_mites": 1.0,
    "leaf_miner": 1.0,
    "yellow_leaf_curl_virus": 1.0,
    "mosaic_virus": 1.0,
}

# ══════════════════════════════════════════════════════
# 病害 → 文献推荐目标值
# ══════════════════════════════════════════════════════
# 格式: { "disease_key": (T_min, T_max, RH_min, RH_max, VPD_min, VPD_max, priority) }
# priority 用于多病害冲突排序 (数值越大越优先)
# 文献来源编号见文件末尾

DIS = {
    # ─── 正常模式 ───
    # 番茄最佳生长 VPD 0.7-1.0 kPa, T 20-26°C, RH 60-80%  [R1,R5]
    "normal":       (20, 26,  60, 80,  0.7, 1.2,  0),

    # ─── 真菌类叶病 (需降湿) ───
    # [R2] Attri 2024: 早疫最适 25-30°C, >90%RH; 抑制需 T<25 且 RH<85
    "early_blight":         (20, 25,  55, 75,  0.8, 1.5,  3),
    # [R3] Maziero 2009: 晚疫最适 18-22°C, >90%RH; >25°C 自然抑制
    "late_blight":          (22, 28,  50, 70,  0.8, 1.5,  4),
    # [R1] Small 1930: 叶霉最适 ~22°C; RH>80%严重, <70%罕见
    "leaf_mold":            (20, 25,  50, 70,  0.8, 1.5,  3),
    # [R2] 斑枯最适 20-25°C, 高湿
    "septoria":             (20, 25,  55, 75,  0.8, 1.5,  2),
    # [R4] 灰霉最适 ~23°C, >80%RH; >30°C 抑制
    "gray_mold":            (22, 28,  50, 70,  0.8, 1.5,  3),

    # ─── 细菌性病害 (需降湿) ───
    # [R6] 细菌性斑点最适 24-30°C, 高湿; 抑制需 RH<80
    "bacterial_spot":       (20, 25,  55, 75,  0.8, 1.5,  3),

    # ─── 虫害: 红蜘蛛 (需增湿!) ───
    # [R7] 红蜘蛛最适 25-35°C, <50%RH; 高湿>60%强烈抑制
    # 需要湿度 >60% 而非常规的降湿 → 和真菌策略冲突
    "spider_mites":         (18, 26,  65, 85,  0.6, 1.0,  5),

    # ─── 虫害: 潜叶蝇 ───
    # [R5] 中湿中温即可
    "leaf_miner":           (20, 26,  55, 80,  0.7, 1.2,  1),

    # ─── 病毒病 (需防媒介昆虫) ───
    # [R8] TYLCV 媒介粉虱最适 25-30°C, 干燥; 低温高湿抑制
    "yellow_leaf_curl_virus": (18, 24,  65, 85,  0.6, 1.0,  4),
    "mosaic_virus":           (18, 24,  60, 80,  0.6, 1.0,  3),
}

# ══════════════════════════════════════════════════════
# 土壤灌溉阈值
# ══════════════════════════════════════════════════════
SOIL_TARGET     = 55.0   # 目标土壤湿度%
SOIL_HYST       = 15.0   # 迟滞带: < target-hyst → 开泵, > target+hyst → 关泵
SOIL_DRY_ALARM  = 25.0   # 严重干旱警告阈值

# ══════════════════════════════════════════════════════
# 文件路径
# ══════════════════════════════════════════════════════
SENSORS_JSON = "/userdata/sensors.json"
PLANTS_JSON  = "/userdata/plants.json"
STATUS_JSON  = "/userdata/actuator.json"
BASE = "/sys/class/gpio"

# ══════════════════════════════════════════════════════
# GPIO 底层
# ══════════════════════════════════════════════════════
SWITCH_GAP = 0.3  # 继电器切换最小间隔秒, 防同时动作

def _write(path, val):
    with open(path, "w") as f:
        f.write(str(val))


_last_switch = 0

def _safe_switch(gpio, value):
    global _last_switch
    gap = SWITCH_GAP - (time.time() - _last_switch)
    if gap > 0:
        time.sleep(gap)
    _write(f"{BASE}/gpio{gpio}/value", value)
    _last_switch = time.time()


def _export(gpio):
    p = f"{BASE}/gpio{gpio}"
    if not os.path.isdir(p):
        _write(f"{BASE}/export", gpio)
        time.sleep(0.1)
    _write(f"{p}/direction", "out")
    _write(f"{p}/value", IDLE)
    return p


# ══════════════════════════════════════════════════════
# VPD 计算 (Tetens 公式)
# ══════════════════════════════════════════════════════
def calc_vpd(temp_c, rh_pct):
    svp = 0.6108 * math.exp(17.27 * temp_c / (temp_c + 237.3))  # kPa
    avp = svp * rh_pct / 100.0
    return round(svp - avp, 2)


# ══════════════════════════════════════════════════════
# 病害态势判定
# ══════════════════════════════════════════════════════
def assess_disease_state():
    """从 plants.json 读取病害, 判定温室整体病害态势。
    返回: {
        "diseases": {disease_key: count},  # 每种病害出现的株数
        "mode": "normal"|disease_key,       # 主导病害模式
        "targets": (T_lo, T_hi, RH_lo, RH_hi, VPD_lo, VPD_hi),
        "conflicts": [...],                 # 冲突描述
        "scanned": N,                       # 已记录株数
    }
    """
    result = {"diseases": {}, "mode": "normal",
              "targets": DIS["normal"], "conflicts": [], "scanned": 0}

    try:
        with open(PLANTS_JSON) as f:
            pdata = json.load(f)
        plants = pdata.get("plants", [])
        scanned = [p for p in plants if p.get("scanned")]
        result["scanned"] = len(scanned)

        for p in scanned:
            d = p.get("disease", "")
            if d and d != "healthy":
                result["diseases"][d] = result["diseases"].get(d, 0) + 1
    except Exception:
        return result

    if not result["diseases"]:
        return result

    # 选出株数最多且 priority 最高的病害作主导模式
    def sort_key(item):
        d, cnt = item
        return (DIS.get(d, DIS["normal"])[6], cnt)  # (priority, count)

    ranked = sorted(result["diseases"].items(), key=sort_key, reverse=True)
    dominant = ranked[0][0]
    result["mode"] = dominant
    result["targets"] = DIS.get(dominant, DIS["normal"])

    # 冲突检测: 红蜘蛛(需高湿) vs 真菌(需低湿)
    has_mites = "spider_mites" in result["diseases"]
    has_fungi = any(d in result["diseases"] for d in
                    ["early_blight", "late_blight", "leaf_mold",
                     "septoria", "gray_mold", "bacterial_spot"])
    if has_mites and has_fungi:
        # 冲突: 取中间值折中
        mites_t = DIS["spider_mites"]
        fungi_t = DIS[dominant] if dominant != "spider_mites" else DIS.get(ranked[1][0], DIS["normal"])
        t_lo = round((mites_t[0] + fungi_t[0]) / 2, 1)
        t_hi = round((mites_t[1] + fungi_t[1]) / 2, 1)
        rh_lo = max(mites_t[2], fungi_t[2])  # 取两者下限较高者
        rh_hi = min(mites_t[3], fungi_t[3])  # 取两者上限较低者
        result["targets"] = (t_lo, t_hi, rh_lo, rh_hi, 0.7, 1.2, result["targets"][6])
        result["conflicts"].append(
            "红蜘蛛(需高湿>65%) vs 真菌类病害(需低湿<75%) → 折中 RH %d-%d%%" % (rh_lo, rh_hi))

    return result


# ══════════════════════════════════════════════════════
# 执行器类
# ══════════════════════════════════════════════════════
class Actuator:
    def __init__(self, name, gpio, min_run=0, min_off=0, cooldown=0, max_run=0):
        self.name = name
        self.gpio = gpio
        self.min_run = min_run
        self.min_off = min_off
        self.cooldown = cooldown
        self.max_run = max_run
        self._path = None
        self._state = False
        self._last_on = 0.0
        self._last_off = 0.0
        self._manual = None       # None=auto, True=manual_on, False=manual_off
        self._manual_until = 0.0
        self._reason = ""         # 最近一次动作原因
        self._init()

    def _init(self):
        try:
            self._path = _export(self.gpio)
        except Exception as e:
            self._path = None
            print(f"[{self.name}] GPIO{self.gpio} 初始化失败: {e}")

    @property
    def available(self):
        return self._path is not None

    def _set(self, on: bool):
        if not self._path:
            return
        _safe_switch(self.gpio, ACTIVE if on else IDLE)
        self._state = on
        if on:
            self._last_on = time.time()
        else:
            self._last_off = time.time()

    def on(self, reason=""):
        if not self._state:
            self._reason = reason
            self._set(True)

    def off(self, reason=""):
        if self._state:
            self._reason = reason
            self._set(False)

    @property
    def is_on(self):
        return self._state

    def elapsed_on(self):
        return time.time() - self._last_on if self._state else 0

    def elapsed_off(self):
        return time.time() - self._last_off if not self._state else 0

    def manual_override(self, on, duration=300):
        self._manual = on
        self._manual_until = time.time() + duration
        self._set(on)
        self._reason = "手动%d秒" % duration

    def _sync_manual_file(self):
        """从 /tmp/actuator_manual.json 读取 Agent 手动覆盖标记"""
        try:
            with open("/tmp/actuator_manual.json") as f:
                m = json.load(f)
            entry = m.get(self.name)
            if entry and time.time() < entry.get("until", 0):
                if not self._manual:
                    self._manual = True
                    self._manual_until = entry["until"]
                    self._set(True)
                    self._reason = "Agent手动"
            elif self._manual is True and self._manual_until > 0:
                # Agent 覆盖已过期
                self._manual = None
                self._manual_until = 0
        except Exception:
            pass

    def update(self, sensors, targets):
        """自动决策, 返回动作描述或 None"""
        now = time.time()

        # ── 跨进程同步 Agent 手动覆盖 ──
        self._sync_manual_file()

        # ── 手动覆盖 ──
        if self._manual is not None:
            if now < self._manual_until:
                if self._state != self._manual:
                    self._set(self._manual)
                return None
            self._manual = None

        # ── 保护期 ──
        if self._state and self.min_run > 0:
            if self.elapsed_on() < self.min_run:
                return None

        if self._state and self.max_run > 0:
            if self.elapsed_on() > self.max_run:
                self.off("超时保护(max_run=%ds)" % self.max_run)
                return "%s: 超时自动关" % self.name

        if not self._state:
            if self.cooldown > 0 and self.elapsed_off() < self.cooldown:
                return None
            if self.min_off > 0 and self.elapsed_off() < self.min_off:
                return None

        # ── 自动决策(子类实现) ──
        return self._decide(sensors, targets)

    def _decide(self, sensors, targets):
        raise NotImplementedError

    def status(self):
        return {
            "name": self.name, "gpio": self.gpio,
            "state": self._state, "available": self.available,
            "manual": self._manual is not None,
            "reason": self._reason,
            "elapsed_on": round(self.elapsed_on(), 1),
            "elapsed_off": round(self.elapsed_off(), 1),
        }


class FanController(Actuator):
    """风扇: 基于温湿度和 VPD 控制排风。

    决策逻辑(P控制器+滞回):
      - VPD 过高(>target_hi+0.2) 且 RH 过低 → 不转(保持湿度)
      - VPD 过低(<target_lo-0.1) 或 RH 过高(>target_hi) → 转(排湿)
      - 温度过高(>T_hi+1) → 转(降温)
      - 温度过低(<T_lo-1) → 不转(保温)
    """

    def _decide(self, sensors, targets):
        t = sensors.get("temp")
        rh = sensors.get("rh")
        if t is None or rh is None:
            return None

        T_lo, T_hi, RH_lo, RH_hi, VPD_lo, VPD_hi, _ = targets
        vpd = calc_vpd(t, rh)

        should_on = False
        reason = ""

        # ① VPD 过低 = 太湿 → 排湿
        if vpd < VPD_lo - 0.1:
            should_on = True
            reason = "VPD %.2f < %.2f kPa(太湿)" % (vpd, VPD_lo)

        # ② RH 过高 → 排湿
        elif rh > RH_hi + 5:
            should_on = True
            reason = "RH %.0f%% > %d%%" % (rh, RH_hi)

        # ③ 温度过高 → 降温
        elif t > T_hi + 1:
            should_on = True
            reason = "T %.1f°C > %.1f°C(过热)" % (t, T_hi)

        # ④ VPD 过高 = 太干 → 不转
        if vpd > VPD_hi + 0.3 and should_on and not (t > T_hi + 1):
            should_on = False
            # 但温度也高时仍需降温

        # ⑤ 温度过低 → 不转(保温)
        if t < T_lo - 2:
            should_on = False

        if should_on and not self._state:
            self.on(reason)
            return "%s: 开(%s)" % (self.name, reason)
        elif not should_on and self._state:
            self.off("条件解除")
            return "%s: 关" % self.name
        return None


class PumpController(Actuator):
    """水泵: 基于土壤湿度迟滞控制。

    决策逻辑:
      - soil < target - hyst → 开(浇水)
      - soil > target + hyst → 关
      - sim_soil=true → 不动作(模拟数据不做灌溉决策)
    """

    def _decide(self, sensors, targets):
        soil = sensors.get("soil")
        sim  = sensors.get("sim_soil", True)
        if soil is None or sim:
            return None

        should_on = soil < SOIL_TARGET - SOIL_HYST
        should_off = soil > SOIL_TARGET + SOIL_HYST

        if should_on and not self._state:
            self.on("土壤湿度 %.0f%% < %.0f%%" % (soil, SOIL_TARGET - SOIL_HYST))
            return "%s: 开(灌溉)" % self.name
        elif should_off and self._state:
            self.off("土壤湿度 %.0f%% >= %.0f%%" % (soil, SOIL_TARGET + SOIL_HYST))
            return "%s: 关(灌溉完成)" % self.name
        return None


class LightController(Actuator):
    """LED 补光: 基于 DLI 目标和病害态势的自动调光。

    文献策略 [R11-R16]:
      - 日间 DLI 目标 22 mol/m²/day, 16h 光周期
      - 环境 lux < 15klux 触发补光, > 25klux 关灯
      - 真菌病害时提升光照 10-20% (增强植物防御酶活性)
      - 光周期 6:00-22:00, 夜间不补光(防光周期伤害)
      - PI 控制器 + 限速: 每周期最多调整 LED_STEP_PCT%
    """

    def __init__(self, name, gpio):
        super().__init__(name, gpio, min_run=0, cooldown=0)
        self._led = None
        try:
            import led_dimmer
            self._led = led_dimmer
        except Exception as e:
            print("[%s] led_dimmer 不可用: %s" % (name, e))

    def _apply(self, pct):
        if self._led:
            self._led.set_brightness(pct)

    def _sync_agent_manual(self):
        """从手动覆盖文件同步 Agent 的灯光控制(含亮度)"""
        try:
            with open("/tmp/actuator_manual.json") as f:
                m = json.load(f)
            entry = m.get("补光灯") or m.get(self.name)
            if entry and time.time() < entry.get("until", 0):
                b = entry.get("brightness", 85)
                if not self._state or self.pct != b:
                    self._apply(b)
                    self._set(True)
                    self.pct = b
                    self._reason = "Agent手动 %d%%" % b
                self._manual = True
                self._manual_until = entry["until"]
        except Exception:
            pass

    def update(self, sensors, targets):
        # LightController 重写: 先同步手动亮度再走父类逻辑
        self._sync_agent_manual()
        return super().update(sensors, targets)

    def _decide(self, sensors, targets):

        if self._manual:
            if time.time() < self._manual_until:
                return None
            self._manual = None
        lux = sensors.get("lux")
        if lux is None:
            return None

        now = datetime.now()
        hour = now.hour
        sim_veml = sensors.get("sim_veml", True)

        # ── 光周期检查 ──
        if hour < LIGHT_ON_HOUR or hour >= LIGHT_OFF_HOUR:
            if self._state:
                self.off("夜间")
                return "%s: 关(夜间)" % self.name
            return None

        # ── 模拟数据不做补光决策 ──
        if sim_veml:
            return None

        # ── 病害光补系数 ──
        _, _, _, _, _, _, priority = targets
        mode = getattr(self, '_disease_mode', 'normal')
        boost = DISEASE_LIGHT_BOOST.get(mode, 1.0)
        target_lux = LUX_TARGET_DAY * boost

        # ── 迟滞逻辑 ──
        if lux > LUX_SUPPLEMENT_OFF:
            if self._state:
                self.off("环境光充足 %.0f lux" % lux)
                return "%s: 关(自然光充足)" % self.name
            return None

        if lux < LUX_SUPPLEMENT_ON:
            # 计算所需补光量, 限速爬升
            deficit = target_lux - lux
            tgt_pct = min(LED_MAX_PCT, max(LED_MIN_PCT,
                          deficit / target_lux * 100.0))
            # 限速
            cur_pct = self.pct if hasattr(self, '_pct') else 0
            nxt = cur_pct + max(-LED_STEP_PCT, min(LED_STEP_PCT,
                                                   tgt_pct - cur_pct))
            if nxt < LED_MIN_PCT:
                nxt = 0

            if nxt > 0:
                self.on("环境 %.0f lux < %.0f, 补光 %d%%" %
                        (lux, LUX_SUPPLEMENT_ON, nxt))
                self._apply(nxt)
                return "%s: %d%% (环境%.0f lux)" % (self.name, nxt, lux)
            elif self._state:
                self.off("补光需求过低")
                self._apply(0)
                return "%s: 关" % self.name
        return None

    def off(self, reason=""):
        super().off(reason)
        if self._led:
            self._led.set_brightness(0)
        self.pct = 0

    def status(self):
        s = super().status()
        s["brightness"] = getattr(self, 'pct', 0)
        s["target_lux"] = LUX_TARGET_DAY
        return s


# ══════════════════════════════════════════════════════
# 全局实例
# ══════════════════════════════════════════════════════
fan  = FanController("风扇", GPIO_FAN,
                     min_run=FAN_MIN_RUN, min_off=FAN_MIN_OFF,
                     cooldown=FAN_COOLDOWN)
pump = PumpController("水泵", GPIO_PUMP,
                      max_run=PUMP_MAX_RUN, cooldown=PUMP_COOLDOWN,
                      min_run=PUMP_MIN_ON)
light = LightController("补光灯", GPIO_LED)


# ══════════════════════════════════════════════════════
# 传感器读取
# ══════════════════════════════════════════════════════
def load_sensors():
    try:
        with open(SENSORS_JSON) as f:
            return json.load(f)
    except Exception:
        return {}


# ══════════════════════════════════════════════════════
# 主控制循环
# ══════════════════════════════════════════════════════
_last_disease_log = 0

def control_cycle():
    global _last_disease_log
    s = load_sensors()
    ds = assess_disease_state()

    # 每 5 分钟输出一次病害态势
    now = time.time()
    if now - _last_disease_log > 300:
        _last_disease_log = now
        if ds["diseases"]:
            print("[病害态势] 模式=%s 病害=%s 已记录=%d/16" % (
                ds["mode"], dict(ds["diseases"]), ds["scanned"]))
            T_lo, T_hi, RH_lo, RH_hi, VPD_lo, VPD_hi, _ = ds["targets"]
            print("  目标: T %.0f-%.0f°C  RH %d-%d%%  VPD %.1f-%.1f kPa" % (
                T_lo, T_hi, RH_lo, RH_hi, VPD_lo, VPD_hi))
            for c in ds["conflicts"]:
                print("  ⚠ %s" % c)

    # 病害模式传递给 LightController
    light._disease_mode = ds["mode"]

    actions = []
    for a in (fan, pump, light):
        act = a.update(s, ds["targets"])
        if act:
            actions.append(act)

    # 写状态文件
    t = s.get("temp"); rh = s.get("rh")
    try:
        with open(STATUS_JSON, "w") as f:
            json.dump({
                "ts": int(now),
                "fan": fan.status(), "pump": pump.status(), "light": light.status(),
                "sensors": {
                    "temp": t, "rh": rh,
                    "vpd": calc_vpd(t, rh) if t and rh else None,
                    "soil": s.get("soil"), "lux": s.get("lux"),
                },
                "disease": {
                    "mode": ds["mode"],
                    "diseases": ds["diseases"],
                    "scanned": ds["scanned"],
                    "conflicts": ds["conflicts"],
                },
                "targets": {
                    "T_lo": ds["targets"][0], "T_hi": ds["targets"][1],
                    "RH_lo": ds["targets"][2], "RH_hi": ds["targets"][3],
                    "VPD_lo": ds["targets"][4], "VPD_hi": ds["targets"][5],
                },
            }, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

    if actions:
        print("[%s] %s" % (time.strftime("%H:%M:%S"), " | ".join(actions)), flush=True)
    return actions


def daemon(interval=5):
    print("作物AI执行器 v2 (病害感知)")
    print("风扇=GPIO%d  水泵=GPIO%d" % (GPIO_FAN, GPIO_PUMP))
    print("病害检测源: %s" % PLANTS_JSON)
    print("传感器源:   %s" % SENSORS_JSON)
    try:
        while True:
            control_cycle()
            time.sleep(interval)
    except KeyboardInterrupt:
        fan.off("退出"); pump.off("退出")
        print("执行器已全部关闭")


# ══════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════
if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--daemon", action="store_true")
    ap.add_argument("--fan", choices=["on", "off"])
    ap.add_argument("--pump", choices=["on", "off"])
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--disease", action="store_true", help="查看当前病害态势")
    ap.add_argument("--interval", type=int, default=5)
    args = ap.parse_args()

    if args.daemon:
        daemon(args.interval)
    elif args.disease:
        ds = assess_disease_state()
        print("病害态势: %s" % ds["mode"])
        print("病害分布: %s" % dict(ds["diseases"]))
        T_lo, T_hi, RH_lo, RH_hi, VPD_lo, VPD_hi, _ = ds["targets"]
        print("目标: T %.0f-%.0f°C  RH %d-%d%%  VPD %.1f-%.1f kPa" % (
            T_lo, T_hi, RH_lo, RH_hi, VPD_lo, VPD_hi))
    elif args.fan:
        fan.manual_override(args.fan == "on")
        print("风扇: %s (手动)" % ("开" if fan.is_on else "关"))
    elif args.pump:
        pump.manual_override(args.pump == "on")
        print("水泵: %s (手动)" % ("开" if pump.is_on else "关"))
    elif args.status:
        for a in (fan, pump, light):
            s = a.status()
            print("%s: GPIO%d %s %s %s" % (
                s["name"], s["gpio"],
                "开" if s["state"] else "关",
                "(手动)" if s["manual"] else "(自动)",
                "[不可用]" if not s["available"] else ""))
        s = load_sensors()
        t, rh = s.get("temp"), s.get("rh")
        if t and rh:
            print("VPD: %.2f kPa (T=%.1f°C RH=%.0f%%)" % (calc_vpd(t, rh), t, rh))
    else:
        control_cycle()
        for a in (fan, pump, light):
            s = a.status()
            print("%s: %s (原因: %s)" % (s["name"],
                  "开" if s["state"] else "关", s["reason"] or "无"))


# ══════════════════════════════════════════════════════
# 参考文献
# ══════════════════════════════════════════════════════
"""
[R1] Small, T. (1930). The relation of atmospheric temperature and humidity to
     tomato leaf mould (Cladosporium fulvum). Annals of Applied Biology, 17(1), 71-80.
     → 叶霉最适 ~22°C; RH>80% 严重, <70% 罕见。

[R2] Attri, M. et al. (2024). Influence of Temperature and Relative Humidity on
     Spore Germination and Early Blight Disease Development of Tomato Caused by
     Alternaria solani. Plant Archives, 25(1), 215-222.
     → 早疫最适 25-30°C, >90%RH 发芽率最高 95%。

[R3] Maziero, J.M.N. et al. (2009). Effects of Temperature on Events in the
     Infection Cycle of Two Clonal Lineages of Phytophthora infestans Causing
     Late Blight on Tomato. Plant Disease, 93(5), 459-466.
     → 晚疫最适 18-22°C, >90%RH; 潜伏期最短 69h@22°C。

[R4] Li, Y. et al. (2023). Effects of Intermittent Temperature and Humidity
     Regulation on Tomato Gray Mold. Plant Disease, 107(5), 1420-1428.
     → 灰霉最适 ~23°C; >80%RH; 间歇调节(4h高T低湿/4h恢复)抑制最佳。

[R5] Shamshiri, R.R. et al. (2018). Review of optimum temperature, humidity,
     and vapour pressure deficit for microclimate evaluation and control in
     greenhouse cultivation of tomato. International Agrophysics, 32, 287-302.
     → 番茄最佳 VPD 0.7-1.0 kPa, T 20-26°C, RH 60-80%。

[R6] Jones, J.B. et al. (1991). Compendium of Tomato Diseases. APS Press.
     → 细菌性斑点最适 24-30°C, 高湿。

[R7] Alabama Cooperative Extension (2023). Spider Mite Scouting & Management
     in Vegetable Crops.
     → 红蜘蛛最适 25-35°C, <50%RH; >60%RH 强烈抑制。

[R8] NC State Extension (2023). Tomato Yellow Leaf Curl Virus.
     → TYLCV 媒介粉虱最适 25-30°C 干燥; 低温高湿抑制。

[R9] Wang, Z. et al. (2024). An optimized approach to hourly temperature and
     humidity setpoint generation for reducing tomato disease and saving power
     cost in greenhouses. Computers and Electronics in Agriculture, 225, 109263.
     → MOGA 优化温室设定点, 平衡病害抑制与能耗。

[R10] MDPI Horticulturae (2026). Climate-Driven Pest and Disease Dynamics in
      Greenhouse Vegetables: A Review. Horticulturae, 12(4), 415.
      → VPD 0.6-1.0 kPa 对多数病害有抑制效果; VPD < 0.4 kPa 高风险区。
"""
