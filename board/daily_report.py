"""每日温室报告 → 微信推送。由 cron 每天早上调用。"""
import json, os, time, sys

sys.path.insert(0, "/userdata/voice")
from wechat_push import send, is_configured
from weather import weather_summary

SENSORS = "/userdata/sensors.json"
PLANTS = "/userdata/plants.json"
CSVLOG = "/userdata/crop_log.csv"


def run():
    if not is_configured():
        print("SendKey not configured")
        return

    parts = []

    # 环境
    try:
        with open(SENSORS) as f:
            s = json.load(f)
        parts.append("## 环境")
        parts.append("温度 %.1f℃  |  湿度 %.0f%%  |  CO2 %d ppm  |  光照 %d lux" %
                     (s.get("temp", 0), s.get("rh", 0), s.get("co2", 0), s.get("lux", 0)))
        soil = s.get("soil")
        if soil is not None:
            parts.append("土壤湿度 %.0f%%" % soil)
    except Exception:
        parts.append("## 环境\n无数据")

    # 选株
    try:
        with open(PLANTS) as f:
            pdata = json.load(f)
        plants = pdata.get("plants", [])
        scanned = [p for p in plants if p.get("scanned")]
        parts.append("\n## 选株（%d/8 已记录）" % len(scanned))
        DIS = {"leaf_mold": "叶霉病", "early_blight": "早疫病", "late_blight": "晚疫病",
               "septoria": "斑枯病", "mosaic_virus": "花叶病毒", "spider_mites": "红蜘蛛",
               "bacterial_spot": "细菌性斑点", "leaf_miner": "潜叶蝇",
               "yellow_leaf_curl_virus": "黄化曲叶病毒"}
        for p in plants:
            pid = p["id"] + 1
            if p.get("scanned"):
                info = []
                if p.get("green"): info.append("青%d" % p["green"])
                if p.get("half"): info.append("半熟%d" % p["half"])
                if p.get("ripe"): info.append("红%d" % p["ripe"])
                dis = p.get("disease")
                if dis:
                    info.append(DIS.get(dis, dis))
                if p.get("est", 0) > 0:
                    info.append("估产%.0fg" % p["est"])
                parts.append("#%d: %s" % (pid, " | ".join(info) if info else "正常"))
            else:
                parts.append("#%d: 未记录" % pid)
    except Exception:
        parts.append("\n## 选株\n无数据")

    # 天气
    try:
        ws = weather_summary()
        if ws:
            parts.append("\n## 天气\n" + ws)
    except Exception:
        pass

    title = "🌱 温室日报 " + time.strftime("%m/%d %H:%M")
    body = "\n".join(parts)
    ok, msg = send(title, body)
    print("Push:", ok, msg)


if __name__ == "__main__":
    run()
