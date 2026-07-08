"""LLM Agent 工具层: 让 LLM 可以读取传感器/控制执行器。
云端 GLM-4-Flash 用原生 function calling, 本地 0.5B 用 prompt 模式降级。"""
import json, time, os

SENSORS  = "/userdata/sensors.json"
PLANTS   = "/userdata/plants.json"
ACTUATOR = "/userdata/actuator.json"

# ── 工具定义 (OpenAI function-calling 兼容格式) ──

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_sensors",
            "description": "获取温室实时传感器数据: 温度、湿度、CO2、光照、土壤湿度",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_actuators",
            "description": "获取风扇、水泵和补光灯的当前状态(开/关/亮度%/手动/自动)",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "control_fan",
            "description": "控制排风扇的开关。温度>30°C或湿度>80%时应开风扇排湿降温。",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["on", "off"]},
                    "duration": {"type": "integer", "description": "手动覆盖时长(秒), 默认300"},
                },
                "required": ["action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "control_pump",
            "description": "控制灌溉水泵的开关。土壤湿度<30%时应开泵浇水。",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["on", "off"]},
                    "duration": {"type": "integer", "description": "手动覆盖时长(秒), 默认300"},
                },
                "required": ["action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "control_light",
            "description": "控制LED补光灯的开关和亮度。光照不足(白天<15klux)时应开灯补光, 上限85%。",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["on", "off", "set"]},
                    "brightness": {"type": "integer", "description": "亮度百分比 0-85, 仅 action=set 时需要"},
                    "duration": {"type": "integer", "description": "手动覆盖时长(秒), 默认600"},
                },
                "required": ["action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_plants",
            "description": "获取16株番茄的逐株记录: 果实计数、病害、估产",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
]

# ── 工具实现 ──

def get_sensors():
    try:
        with open(SENSORS) as f:
            d = json.load(f)
        return json.dumps({
            "温度": f"{d.get('temp','?')}°C",
            "湿度": f"{d.get('rh','?')}%",
            "CO2": f"{d.get('co2','?')}ppm",
            "光照": f"{d.get('lux','?')}lux",
            "土壤湿度": f"{d.get('soil','?')}%",
            "数据来源": {k: "真实" if not d.get(f"sim_{k[0:3]}", True)
                         else "模拟" for k in ["temp", "soil", "lux"]},
        }, ensure_ascii=False)
    except Exception:
        return "传感器数据暂不可用"


def get_actuators():
    try:
        with open(ACTUATOR) as f:
            d = json.load(f)
        fan, pump = d.get("fan", {}), d.get("pump", {})
        light = d.get("light", {})
        return json.dumps({
            "风扇": f"{'开' if fan.get('state') else '关'}"
                   f"{'(手动)' if fan.get('manual') else '(自动)'}",
            "水泵": f"{'开' if pump.get('state') else '关'}"
                   f"{'(手动)' if pump.get('manual') else '(自动)'}",
            "补光灯": f"{light.get('brightness', 0)}%"
                     f"{'(手动)' if light.get('manual') else '(自动)'}",
        }, ensure_ascii=False)
    except Exception:
        return "执行器状态暂不可用"


# 手动覆盖标记文件, 供 actuator daemon 跨进程读取
MANUAL_FILE = "/tmp/actuator_manual.json"

# GPIO 底层 (直接写, 不经过 actuator 模块避免跨进程状态不同步)
BASE = "/sys/class/gpio"
ACTIVE = 0   # 低电平有效
IDLE   = 1
SWITCH_GAP = 0.3  # 继电器切换最小间隔秒, 防同时动作浪涌+EMI叠加


def _write(path, val):
    with open(path, "w") as f:
        f.write(str(val))


def _ensure_gpio(gpio):
    p = f"{BASE}/gpio{gpio}"
    if not os.path.isdir(p):
        _write(f"{BASE}/export", gpio)
        time.sleep(0.1)
    _write(f"{p}/direction", "out")
    return p


_last_switch = 0  # 全局上次切换时间戳


def _safe_switch(gpio, value):
    """带间隔保护的 GPIO 切换, 防止同时动作导致电源浪涌叠加"""
    global _last_switch
    gap = SWITCH_GAP - (time.time() - _last_switch)
    if gap > 0:
        time.sleep(gap)
    _write(f"{BASE}/gpio{gpio}/value", value)
    _last_switch = time.time()


def _control(name, gpio, action, duration=300):
    """直接控制 GPIO + 写手动覆盖标记"""
    try:
        _ensure_gpio(gpio)
        path = f"{BASE}/gpio{gpio}"
        manual = {}
        try:
            with open(MANUAL_FILE) as f:
                manual = json.load(f)
        except Exception:
            pass

        if action == "on":
            _safe_switch(gpio, ACTIVE)
            manual[name] = {"until": int(time.time() + duration)}
            msg = f"{name}已开启，{duration}秒后恢复自动控制"
        else:
            _safe_switch(gpio, IDLE)
            manual.pop(name, None)
            msg = f"{name}已关闭，恢复自动控制"

        tmp = MANUAL_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(manual, f)
        os.replace(tmp, MANUAL_FILE)
        return msg
    except Exception as e:
        return f"{name}控制失败: GPIO{gpio} 不可用 ({e})"


def control_fan(action, duration=300):
    return _control("fan", 129, action, duration)   # GPIO4_A1


def control_pump(action, duration=300):
    return _control("pump", 111, action, duration)  # GPIO3_B7


def control_light(action="on", brightness=85, duration=600):
    """控制 LED 补光灯: on=全亮(85%), off=关, set=brightness%。写手动覆盖标记。"""
    try:
        import led_dimmer
        if action == "on":
            pct = 85
            led_dimmer.set_brightness(85)
            msg = "补光灯已开启(85%)"
        elif action == "off":
            pct = 0
            led_dimmer.set_brightness(0)
            msg = "补光灯已关闭"
        elif action == "set":
            pct = max(0, min(85, int(brightness)))
            led_dimmer.set_brightness(pct)
            msg = f"补光灯亮度已设为{pct}%"

        # 写手动覆盖标记, 供 actuator daemon 读取
        manual = {}
        try:
            with open(MANUAL_FILE) as f:
                manual = json.load(f)
        except Exception:
            pass
        if pct > 0:
            manual["补光灯"] = {"until": int(time.time() + duration), "brightness": pct}
        else:
            manual.pop("补光灯", None)
        tmp = MANUAL_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(manual, f)
        os.replace(tmp, MANUAL_FILE)
        return msg
    except Exception as e:
        return f"补光灯控制失败: {e}"


def get_plants():
    try:
        with open(PLANTS) as f:
            d = json.load(f)
        plants = d.get("plants", [])
        lines = []
        for p in plants:
            pid = p["id"] + 1
            if not p.get("scanned"):
                lines.append(f"第{pid}株: 未记录")
                continue
            info = []
            if p.get("green"): info.append(f"青果{p['green']}个")
            if p.get("half"): info.append(f"半熟{p['half']}个")
            if p.get("ripe"): info.append(f"红果{p['ripe']}个")
            if p.get("disease"): info.append(f"病害:{p['disease']}")
            if p.get("est", 0) > 0: info.append(f"估产{p['est']}g")
            lines.append(f"第{pid}株: {', '.join(info) if info else '已记录(无异常)'}")
        return json.dumps({"当前株": d.get("current", -1) + 1,
                           "已记录": f"{len([p for p in plants if p.get('scanned')])}/16",
                           "详情": lines}, ensure_ascii=False)
    except Exception:
        return "植株数据暂不可用"


# ── 工具调度 ──

TOOL_MAP = {
    "get_sensors": get_sensors,
    "get_actuators": get_actuators,
    "control_fan": control_fan,
    "control_pump": control_pump,
    "control_light": control_light,
    "get_plants": get_plants,
}


def execute_tool(name, args):
    fn = TOOL_MAP.get(name)
    if not fn:
        return f"未知工具: {name}"
    try:
        return fn(**args)
    except Exception as e:
        return f"工具执行失败: {e}"


# ── 本地 0.5B prompt 模式工具解析 ──
# 0.5B 做不了标准 function calling, 在 system prompt 中注入工具说明,
# LLM 输出 <tool>name|arg=val,...</tool> 时解析并执行

TOOL_PROMPT = """你可以使用以下工具来获取实时数据和控制设备:
| 工具 | 用途 | 参数 |
| get_sensors | 获取温湿度/CO2/光照/土壤 | 无 |
| get_actuators | 获取风扇水泵状态 | 无 |
| get_plants | 获取16株番茄记录 | 无 |
| control_fan | 开关风扇(排湿降温) | action=on/off |
| control_pump | 开关水泵(灌溉) | action=on/off |
| control_light | 控制补光灯(补光) | action=on/off/set, brightness=0-85 |
需要调用工具时, 在回答中插入 <tool>工具名|参数=值</tool>。
例如: <tool>control_fan|action=on</tool> 表示开风扇。
调用工具后会收到工具返回结果, 然后继续回答。"""


def parse_local_tool(text):
    """从本地 LLM 输出中提取 <tool>...</tool>"""
    import re
    m = re.search(r'<tool>(.*?)</tool>', text)
    if not m:
        return None, text
    inner = m.group(1)
    parts = inner.split("|")
    name = parts[0].strip()
    args = {}
    for p in parts[1:]:
        kv = p.split("=", 1)
        if len(kv) == 2:
            k, v = kv[0].strip(), kv[1].strip()
            if v.isdigit():
                v = int(v)
            args[k] = v
    clean = re.sub(r'<tool>.*?</tool>', '', text).strip()
    return (name, args), clean
