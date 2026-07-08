import os, json, time, urllib.request

CACHE = "/userdata/voice/weather_cache.json"
LOC_CACHE = "/userdata/voice/location_cache.json"
TEMP = "/userdata/voice/weather_tmp.json"

# 天气代码→中文
WMO = {0:"晴",1:"少云",2:"多云",3:"阴",45:"雾",48:"霜雾",51:"小雨",53:"中雨",
       55:"大雨",61:"阵雨",63:"中阵雨",65:"大阵雨",71:"小雪",73:"中雪",75:"大雪",
       77:"雨夹雪",80:"雷阵雨",82:"大雷雨",85:"暴雪",95:"雷暴",96:"冰雹雷暴",99:"大冰雹雷暴"}

TTL_WEATHER = 1800   # 30分钟
TTL_LOC = 86400      # 24小时


def _fetch(url, timeout=10):
    try:
        r = urllib.request.urlopen(url, timeout=timeout)
        return json.loads(r.read())
    except Exception:
        return None


def _load(path, max_age):
    try:
        with open(path) as f:
            d = json.load(f)
        if time.time() - d.get("ts", 0) < max_age:
            return d
    except Exception:
        pass
    return None


def get_location():
    """获取位置: 缓存24h > IP定位 > 默认值"""
    d = _load(LOC_CACHE, TTL_LOC)
    if d and d.get("lat"):
        return d
    j = _fetch("http://ip-api.com/json/?lang=zh-CN")
    if j and j.get("lat"):
        d = {"ts": time.time(), "lat": j["lat"], "lon": j["lon"],
             "city": j.get("city",""), "region": j.get("regionName",""),
             "country": j.get("country","")}
        try:
            with open(LOC_CACHE, "w") as f:
                json.dump(d, f)
        except OSError:
            pass
        return d
    # 默认: 莆田
    return {"ts": 0, "lat": 25.44, "lon": 119.01, "city": "莆田", "region": "福建"}


def get_weather(lat=None, lon=None):
    """获取当前天气+3日预报, 缓存30min。原子写防崩溃丢缓存。"""
    d = _load(CACHE, TTL_WEATHER)
    if d and d.get("current"):
        return d
    if lat is None or lon is None:
        loc = get_location()
        lat, lon = loc["lat"], loc["lon"]
    url = (f"https://api.open-meteo.com/v1/forecast?"
           f"latitude={lat}&longitude={lon}"
           f"&current=temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m,wind_direction_10m"
           f"&daily=temperature_2m_max,temperature_2m_min,precipitation_sum,weather_code,wind_speed_10m_max"
           f"&timezone=Asia/Shanghai&forecast_days=4")
    j = _fetch(url)
    if not j:
        return d or {}
    j["ts"] = time.time()
    try:
        with open(TEMP, "w") as f:
            json.dump(j, f)
        os.replace(TEMP, CACHE)
    except OSError:
        pass
    return j


def weather_summary():
    """生成给LLM的天气摘要文本"""
    w = get_weather()
    if not w or "current" not in w:
        return ""
    c = w["current"]
    code = c.get("weather_code", 0)
    desc = WMO.get(code, f"代码{code}")
    lines = [f"室外天气：{desc}，{c['temperature_2m']}°C，湿度{c['relative_humidity_2m']}%，"
             f"风速{c.get('wind_speed_10m','?')}m/s"]
    daily = w.get("daily", {})
    dates = daily.get("time", [])
    if dates:
        parts = []
        for i, d in enumerate(dates[:3]):
            wc = daily.get("weather_code", [0]*4)[i]
            hi = daily.get("temperature_2m_max", [0]*4)[i]
            lo = daily.get("temperature_2m_min", [0]*4)[i]
            rain = daily.get("precipitation_sum", [0]*4)[i]
            ds = WMO.get(wc, f"代码{wc}")
            s = f"{d[5:]}: {ds} {lo}-{hi}°C"
            if rain and rain > 0.5:
                s += f" 降雨{rain:.0f}mm"
            parts.append(s)
        lines.append("未来3天：" + "；".join(parts))
    loc = get_location()
    if loc.get("city"):
        lines.append(f"参考位置：{loc['city']}")
    return "\n".join(lines)


if __name__ == "__main__":
    print(weather_summary())
