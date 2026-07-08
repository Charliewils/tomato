"""Server酱微信推送: https://sct.ftqq.com 注册获取 SendKey"""
import urllib.request, urllib.parse, json, time

CONFIG = "/userdata/voice/wechat_config.json"
API = "https://sctapi.ftqq.com"


def _cfg():
    try:
        with open(CONFIG) as f:
            return json.load(f)
    except Exception:
        return {}


def send(title, content="", channel=None):
    """推送微信消息。channel=9 是方糖服务号, 留空用默认"""
    key = _cfg().get("sendkey", "")
    if not key:
        return False, "未配置 SendKey"
    try:
        data = urllib.parse.urlencode({
            "title": title[:32],       # 标题限 32 字
            "desp": content[:65536],   # 内容限 64KB
        }).encode("utf-8")
        url = f"{API}/{key}.send"
        if channel:
            url += f"?channel={channel}"
        r = urllib.request.urlopen(url, data=data, timeout=10)
        d = json.loads(r.read())
        ok = d.get("code") == 0
        return ok, d.get("message", "")
    except Exception as e:
        return False, str(e)[:100]


def is_configured():
    return bool(_cfg().get("sendkey", ""))


# ── 温室专用便捷函数 ──

def alert_disease(plant_id, disease_cn, suggestion=""):
    """病害告警"""
    body = f"第{plant_id}株检测到{disease_cn}"
    if suggestion:
        body += f"\n建议：{suggestion}"
    return send(f"⚠️ 病害告警：{disease_cn}", body)


def daily_report(env, plants_summary, weather=""):
    """每日摘要（可配 cron 定时发）"""
    body = f"## 环境\n{env}\n\n## 选株\n{plants_summary}"
    if weather:
        body += f"\n\n## 天气\n{weather}"
    return send("🌱 温室日报 " + time.strftime("%m/%d"), body)


def alert_abnormal(temp=None, rh=None, co2=None):
    """异常告警"""
    msgs = []
    if temp and (temp > 35 or temp < 10):
        msgs.append(f"温度异常：{temp}℃")
    if rh and rh > 90:
        msgs.append(f"湿度偏高：{rh}%")
    if co2 and co2 > 2000:
        msgs.append(f"CO2偏高：{co2}ppm")
    if msgs:
        return send("🚨 温室异常", "\n".join(msgs))
    return True, "正常"


if __name__ == "__main__":
    print("configured:", is_configured())
    if is_configured():
        ok, msg = send("板子测试", "来自RV1126B的推送测试 " + time.strftime("%H:%M"))
        print("send:", ok, msg)
