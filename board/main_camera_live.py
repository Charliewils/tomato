import cv2, time, os, csv, sys, json, subprocess, math, threading
import numpy as np
from datetime import datetime
from collections import deque
from PIL import Image, ImageDraw, ImageFont
from rknnpool.rknnpool_ld import rknnPoolExecutor
from func.func_yolov8_optimize import myFunc, CN, DISEASE_NAMES, FRUIT_WEIGHT_G, ADVICE, estimate_yield, _find, set_detect_mode, FRUIT_MODE_YIELD_CORR
import socket

SENSORS = "/userdata/sensors.json"
_PRED = {"loaded": False, "m": None}
_FC = {"v": None, "days": 0}                # 未来7天产量预测缓存(滑窗外, 按日志节奏刷新)


def _predictor():
    if not _PRED["loaded"]:
        _PRED["loaded"] = True
        try:
            yi = _find("yield_inference.py")
            d = os.path.dirname(yi) if yi else None
            if d and d not in sys.path:
                sys.path.insert(0, d)
            from yield_inference import YieldPredictorCPU
            npz = _find("yield_predictor_params.npz")
            _PRED["m"] = YieldPredictorCPU(npz) if npz else None
        except Exception:
            _PRED["m"] = None
    return _PRED["m"]


def _sensor_temp():
    try:
        with open(SENSORS) as f:
            t = json.load(f).get("temp")
        return float(t) if isinstance(t, (int, float)) else 25.0
    except Exception:
        return 25.0


def forecast_7d(sm):                        # 历史按天聚合: 今日=当前滑窗, 前3天=CSV日均
    pred = _predictor()
    if pred is None:
        return None, 0
    rows = []
    if os.path.exists(CSVPATH):
        try:
            with open(CSVPATH, newline="") as f:
                rows = list(csv.DictReader(f))
        except OSError:
            rows = []
    today = datetime.now().strftime("%Y-%m-%d")
    byday = {}
    for r in rows:
        d = (r.get("time") or "")[:10]
        if d and d < today:
            byday.setdefault(d, []).append(r)
    past = sorted(byday)[-3:][::-1]

    def dm(recs, k):
        try:
            return round(sum(float(x.get(k, 0) or 0) for x in recs) / len(recs))
        except Exception:
            return 0
    gc = [sm.get("green", 0)] + [dm(byday[d], "green") for d in past]
    hc = [sm.get("half_ripened", 0)] + [dm(byday[d], "half_ripened") for d in past]
    fc = [sm.get("fully_ripened", 0)] + [dm(byday[d], "fully_ripened") for d in past]
    try:
        feats = pred.build_features(gc, hc, fc, None, 7, temp_avg=_sensor_temp(), par=400.0)
        return float(pred.predict(feats)), len(past) + 1
    except Exception:
        return None, 0
try:
    import qrcode
    _HAS_QR = True
except Exception:
    _HAS_QR = False

DEV = "/dev/video52"
CW, CH = 1024, 600
CAMW, CAMH = 720, 540          # 摄像头区(左上)
COLX = CAMW                    # 右栏 x 起点, 宽 304
BARY = CAMH                    # 底栏 y 起点, 高 60
F = "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"
f14, f16, f18, f20, f22, f26 = [ImageFont.truetype(F, s) for s in (14, 16, 18, 20, 22, 26)]
# 绿白清新风(白底深字), 与网页大屏统一: CYAN→蓝 YEL→深绿(分区标题) GRN→绿 RED→红 WHT→白(按钮字) GRY→灰绿
CYAN, YEL, GRN, RED, WHT, GRY = (31, 122, 140), (31, 122, 70), (33, 138, 70), (200, 62, 62), (255, 255, 255), (110, 125, 117)
BLU = (31, 122, 140)
PUR = (122, 92, 192)
INK = (35, 51, 44)         # 主文字(深墨绿)
AMB = (176, 120, 20)       # 琥珀(半熟/提示)
BG = (244, 247, 242)       # 浅底
CARD = (255, 255, 255)     # 卡片白
LINE = (210, 224, 214)     # 分隔线

DETECT_MODES = ["both", "fruit", "disease"]
MODE_LABEL = {"both": "综合检测", "fruit": "仅果实", "disease": "仅病叶"}
MODE_HINT = {"both": "果实+病叶", "fruit": "退远拍全株果", "disease": "贴近拍病叶"}

CTRL = {"exposure_time_absolute": [800, 100, 4000, 200], "gain": [32, 0, 63, 4],
        "brightness": [0, -64, 64, 16], "contrast": [38, 0, 63, 6], "saturation": [53, 0, 128, 12]}
RGB = {"r": [100, 40, 200, 10], "g": [100, 40, 200, 10], "b": [100, 40, 200, 10]}  # 软件逐通道增益(%);v4l2无独立R/G/B,只能软件做,100=原样
ROWS = [("自动曝光", "auto"), ("曝光", "exposure_time_absolute"), ("增益", "gain"),
        ("亮度", "brightness"), ("对比度", "contrast"), ("饱和度", "saturation"),
        ("红 R", "rgb_r"), ("绿 G", "rgb_g"), ("蓝 B", "rgb_b"), ("音量", "volume")]
auto_exp = [True]


def setc(k):
    os.system("v4l2-ctl -d %s -c %s=%d 2>/dev/null" % (DEV, k, CTRL[k][0]))


def set_auto(on):
    auto_exp[0] = on
    os.system("v4l2-ctl -d %s -c auto_exposure=%d 2>/dev/null" % (DEV, 3 if on else 1))
    if not on:
        setc("exposure_time_absolute")


def gstr(x):
    return "%.2f kg" % (x/1000.0) if x >= 1000 else "%d g" % x


def wrap(s, n):
    return [s[i:i+n] for i in range(0, len(s), n)]


def pil_new(w, h):
    img = Image.new("RGB", (w, h), BG)
    return img, ImageDraw.Draw(img)


def btn(d, x1, y1, x2, y2, label, font, fill, tc=(20, 20, 20)):
    d.rectangle((x1, y1, x2, y2), fill=fill)
    w = d.textlength(label, font=font)
    d.text((x1+(x2-x1-w)/2, y1+(y2-y1-font.size)/2-2), label, font=font, fill=tc)


def to_bgr(pil):
    return cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)


_rgblut = {"key": None, "lut": None}


def apply_rgb(frame):
    r, g, b = RGB["r"][0], RGB["g"][0], RGB["b"][0]
    if r == 100 and g == 100 and b == 100:
        return frame
    if (r, g, b) != _rgblut["key"]:
        x = np.arange(256, dtype=np.float32)
        lut = np.empty((1, 256, 3), np.uint8)
        lut[0, :, 0] = np.clip(x*b/100, 0, 255)
        lut[0, :, 1] = np.clip(x*g/100, 0, 255)
        lut[0, :, 2] = np.clip(x*r/100, 0, 255)
        _rgblut.update(key=(r, g, b), lut=lut)
    return cv2.LUT(frame, _rgblut["lut"])


WEB_PORT = 8080
TUNNEL_URL_FILE = "/userdata/tunnel_url.txt"     # crop-tunnel 服务写入的 cloudflared 公网URL
_QR = {"img": None, "url": ""}


def _board_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return None


def _public_url():                  # 公网隧道URL(任意网络可扫码访问), 由 crop-tunnel.service 落地
    try:
        with open(TUNNEL_URL_FILE) as f:
            u = f.read().strip()
        if u.startswith("https://") and "trycloudflare.com" in u:
            return u
    except OSError:
        pass
    return None


def web_url():                      # 优先公网隧道URL, 缺失退局域网IP(同wifi可访问)
    pub = _public_url()
    if pub:
        return pub
    ip = _board_ip()
    return "http://%s:%d" % (ip, WEB_PORT) if ip else ""


def build_qr(url, target=104):
    _QR["url"] = url
    if not _HAS_QR or not url:
        _QR["img"] = None
        return
    try:
        qr = qrcode.QRCode(border=2, box_size=1)
        qr.add_data(url)
        qr.make(fit=True)
        m = qr.get_matrix()
        n = len(m)
        scale = max(2, target // n)
        side = n * scale
        arr = np.full((side, side, 3), 255, np.uint8)
        for yy in range(n):
            row = m[yy]
            for xx in range(n):
                if row[xx]:
                    arr[yy*scale:(yy+1)*scale, xx*scale:(xx+1)*scale] = 0
        _QR["img"] = Image.fromarray(arr)
    except Exception:
        _QR["img"] = None


def refresh_qr():                   # URL变化(隧道启动延迟/重连换URL)时重建二维码
    url = web_url()
    if url != _QR["url"]:
        build_qr(url)


_info = {"key": None, "img": None}


def sidebar_info(counts, areas=None, mode="both", cur=0):
    g, h, r = counts.get("green", 0), counts.get("half_ripened", 0), counts.get("fully_ripened", 0)
    dis = [(n, counts[n]) for n in DISEASE_NAMES if counts.get(n, 0) > 0]
    fc, fdays = _FC["v"], _FC["days"]
    fckey = (int(fc / 50) if fc is not None else None, fdays >= 2)
    show_fruit, show_dis = mode != "disease", mode != "fruit"
    key = (g, h, r, tuple(dis), fckey, mode, _QR["url"], cur, len(plant_rec))
    if key == _info["key"]:
        return _info["img"]
    _, wt_t, wt_r = estimate_yield(counts, areas)
    pil, d = pil_new(304, CH)
    d.text((12, 8), "作物AI检测", font=f26, fill=CYAN)
    if _QR["img"] is not None:
        pil.paste(_QR["img"], (304 - _QR["img"].width - 6, 6))
    y = 42
    d.text((12, y), "● %s" % MODE_LABEL[mode], font=f16, fill=PUR); y += 22
    d.text((12, y), "第 %d 株 · 记录 %d/%d" % (cur + 1, len(plant_rec), PLANT_N), font=f14, fill=GRY); y += 22

    d.text((10, y), "产量估算", font=f22, fill=YEL); y += 32
    if show_fruit:
        d.text((18, y), "青果 %d    半熟 %d" % (g, h), font=f20, fill=INK); y += 28
        d.text((18, y), "红果(可采收) %d" % r, font=f20, fill=RED); y += 26
        d.text((18, y), "  估重 ~%s" % gstr(wt_r), font=f18, fill=(190, 92, 92)); y += 26
        d.text((18, y), "预计总产 ~%s" % gstr(wt_t), font=f18, fill=GRN); y += 26
        if mode == "fruit":
            d.text((18, y), "（远摄补正 ×%.2f）" % FRUIT_MODE_YIELD_CORR, font=f14, fill=GRY); y += 22
        if fc is not None and fdays >= 2:
            d.text((18, y), "未来7天可采 ~%s" % gstr(fc), font=f18, fill=CYAN); y += 28
        elif fc is not None:
            d.text((18, y), "未来7天预测 (数据积累中)", font=f16, fill=GRY); y += 26
    else:
        d.text((18, y), "仅病叶模式 · 已暂停", font=f18, fill=GRY); y += 28
    y += 6

    d.text((10, y), "病害预警", font=f22, fill=YEL); y += 32
    if not show_dis:
        d.text((18, y), "仅果实模式 · 已关闭", font=f18, fill=GRY); y += 28
    elif dis:
        for n, c in dis[:3]:
            d.text((18, y), "- %s x%d" % (CN[n], c), font=f20, fill=RED); y += 28
    else:
        d.text((18, y), "未发现病害 (正常)", font=f20, fill=GRN); y += 28
    if show_dis:
        y += 8
        d.text((10, y), "防治建议", font=f20, fill=YEL); y += 30
        if dis:
            for n, c in dis[:2]:
                d.text((14, y), CN[n] + ":", font=f18, fill=AMB); y += 24
                for ln in wrap(ADVICE[n], 16):
                    d.text((22, y), ln, font=f16, fill=GRY); y += 21
                y += 4
        else:
            d.text((14, y), "植株健康, 保持通风与", font=f16, fill=GRY); y += 21
            d.text((14, y), "适宜水肥即可", font=f16, fill=GRY)
    if _QR["url"]:
        pub = "trycloudflare.com" in _QR["url"]
        d.text((10, CH-24), "扫码访问 · 公网可用" if pub else ("网页 " + _QR["url"]), font=f16, fill=CYAN)
    _info.update(key=key, img=to_bgr(pil))
    return _info["img"]


def _rowy(i):
    return 38 + i*54


def adj_rects():            # 画布坐标: 可点区域 -> 动作
    R = []
    for i, (lbl, key) in enumerate(ROWS):
        y = _rowy(i)
        if key == "auto":
            R.append((COLX+150, y-4, COLX+296, y+38, ("toggle_auto",)))
        else:
            R.append((COLX+150, y-4, COLX+196, y+38, ("dec", key)))
            R.append((COLX+250, y-4, COLX+296, y+38, ("inc", key)))
    return R


_adj = {"key": None, "img": None}
RGB_COL = {"rgb_r": RED, "rgb_g": GRN, "rgb_b": BLU}


def _aval(k):
    if k == "volume":
        return VOL[0]
    return RGB[k[4:]][0] if k.startswith("rgb_") else CTRL[k][0]


def sidebar_adjust():
    key = (auto_exp[0],) + tuple(_aval(k) for _, k in ROWS if k != "auto")
    if key == _adj["key"]:
        return _adj["img"]
    pil, d = pil_new(304, CH)
    d.text((12, 8), "图像调节", font=f20, fill=YEL)
    for i, (lbl, k) in enumerate(ROWS):
        y = _rowy(i)
        d.text((10, y), lbl, font=f20, fill=RGB_COL.get(k, INK))
        if k == "auto":
            on = auto_exp[0]
            btn(d, 150, y-4, 296, y+38, "自动" if on else "手动", f20, (46, 158, 91) if on else (150, 165, 157), WHT)
        else:
            if k == "exposure_time_absolute" and auto_exp[0]:
                val = "AUTO"
            elif k == "volume":
                val = "%d%%" % VOL[0]
            elif k.startswith("rgb_"):
                val = "%d%%" % RGB[k[4:]][0]
            else:
                val = str(CTRL[k][0])
            btn(d, 150, y-4, 196, y+38, "-", f22, (110, 150, 162), WHT)
            d.text((206, y), val, font=f18, fill=CYAN)
            btn(d, 250, y-4, 296, y+38, "+", f22, (110, 150, 162), WHT)
    d.text((8, CH-24), "调好后再点[图像调节]关闭", font=f14, fill=GRY)
    _adj.update(key=key, img=to_bgr(pil))
    return _adj["img"]


BTN_MODE = (12, BARY+10, 145, CH-8)
BTN_PLANT = (152, BARY+10, 285, CH-8)
BTN_ADJ = (292, BARY+10, 425, CH-8)
BTN_VOICE = (432, BARY+10, 565, CH-8)
BTN_QUIT = (572, BARY+10, 705, CH-8)
BTN_PUSH = (940, BARY+10, 1008, CH-10)   # 右下角推送铃铛
_bar = {"img": None, "mode": None}


def bottombar(mode):
    if _bar["img"] is None or _bar["mode"] != mode:
        pil, d = pil_new(CAMW, CH-BARY)
        btn(d, BTN_MODE[0], 10, BTN_MODE[2], CH-BARY-8, MODE_LABEL[mode], f18, (122, 92, 192), WHT)
        btn(d, BTN_PLANT[0], 10, BTN_PLANT[2], CH-BARY-8, "选株", f18, (46, 158, 91), WHT)
        btn(d, BTN_ADJ[0], 10, BTN_ADJ[2], CH-BARY-8, "图像调节", f18, (31, 122, 140), WHT)
        btn(d, BTN_VOICE[0], 10, BTN_VOICE[2], CH-BARY-8, "语音问答", f18, (40, 150, 140), WHT)
        btn(d, BTN_QUIT[0], 10, BTN_QUIT[2], CH-BARY-8, "退出", f18, (205, 84, 84), WHT)
        _bar.update(img=to_bgr(pil), mode=mode)
    return _bar["img"]


# ---- 逐株选择 + 手动记录 (内存, 重启清零) ----
PLANT_N = 8           # 两边土壤各4株, 与温室模型 earth2 双床一致
FRUIT_KEYS = ["green", "half_ripened", "fully_ripened"]
plant_rec = {}                       # id(0..15) -> {green,half_ripened,fully_ripened,areas,diseases,est_total,est_ripe,ts}


def record_plant(pid, sm, areas):    # 手动确认: 把当前平滑读数快照存入该株
    rec = {k: sm.get(k, 0) for k in FRUIT_KEYS}
    rec["areas"] = {k: areas[k] for k in FRUIT_KEYS if areas and areas.get(k)}
    rec["diseases"] = {n: sm[n] for n in DISEASE_NAMES if sm.get(n, 0) > 0}
    _, tot, ripe = estimate_yield(rec, rec["areas"])
    rec["est_total"], rec["est_ripe"], rec["ts"] = tot, ripe, time.time()
    plant_rec[pid] = rec


def plant_summary():
    g = sum(v["green"] for v in plant_rec.values())
    h = sum(v["half_ripened"] for v in plant_rec.values())
    r = sum(v["fully_ripened"] for v in plant_rec.values())
    tot = sum(v["est_total"] for v in plant_rec.values())
    return len(plant_rec), g, h, r, tot


PLANTS_JSON = "/userdata/plants.json"    # 供 crop_web /api/plants -> 数字孪生镜像逐株真实记录


def load_plants_json():
    """启动时从磁盘恢复选株记录, 断电/重启不丢"""
    global plant_rec
    try:
        with open(PLANTS_JSON) as f:
            d = json.load(f)
        for p in d.get("plants", []):
            if p.get("scanned"):
                plant_rec[p["id"]] = {
                    "green": p.get("green", 0),
                    "half_ripened": p.get("half", 0),
                    "fully_ripened": p.get("ripe", 0),
                    "areas": p.get("areas", {}),
                    "diseases": {p["disease"]: p.get("disease_count", 1)}
                                 if p.get("disease") else {},
                    "est_total": p.get("est", 0),
                    "est_ripe": 0,
                    "ts": d.get("ts", time.time()),
                }
        print("[plants] 从磁盘恢复 %d 株记录" % len(plant_rec), flush=True)
    except Exception:
        print("[plants] 无历史记录, 开始新会话", flush=True)


def write_plants_json(cur):              # 原子写, 防web读到半截
    plants = []
    for i in range(PLANT_N):
        rr = plant_rec.get(i)
        if rr:
            dis = max(rr["diseases"], key=rr["diseases"].get) if rr["diseases"] else None
            plants.append({"id": i, "scanned": True, "green": rr["green"], "half": rr["half_ripened"],
                           "ripe": rr["fully_ripened"], "disease": dis, "est": round(rr["est_total"], 1)})
        else:
            plants.append({"id": i, "scanned": False, "green": 0, "half": 0, "ripe": 0, "disease": None, "est": 0})
    K, g, h, r, tot = plant_summary()
    data = {"ts": time.time(), "current": cur, "count": K, "plants": plants,
            "summary": {"green": g, "half": h, "ripe": r, "est": round(tot, 1)}}
    try:
        tmp = PLANTS_JSON + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, PLANTS_JSON)
    except OSError:
        pass


PG_X0, PG_Y0, PG_W, PG_H, PG_GX, PG_GY = 12, 40, 65, 50, 71, 60   # 4x4 网格几何(面板内坐标)
PBTN_REC = (12, 350, 292, 398)
PBTN_CLR = (12, 406, 292, 442)


def _pcell(i):
    c, r = i % 4, i // 4
    x, y = PG_X0 + c * PG_GX, PG_Y0 + r * PG_GY
    return x, y, x + PG_W, y + PG_H


def plant_rects():                   # 画布坐标 -> 动作
    R = []
    for i in range(PLANT_N):
        x1, y1, x2, y2 = _pcell(i)
        R.append((COLX + x1, y1, COLX + x2, y2, ("plant", i)))
    R.append((COLX + PBTN_REC[0], PBTN_REC[1], COLX + PBTN_REC[2], PBTN_REC[3], ("record",)))
    R.append((COLX + PBTN_CLR[0], PBTN_CLR[1], COLX + PBTN_CLR[2], PBTN_CLR[3], ("clear",)))
    return R


_pp = {"key": None, "img": None}


def plant_panel(cur):
    key = (cur, tuple((i, plant_rec[i]["green"], plant_rec[i]["half_ripened"],
                       plant_rec[i]["fully_ripened"], bool(plant_rec[i]["diseases"])) for i in sorted(plant_rec)))
    if key == _pp["key"]:
        return _pp["img"]
    pil, d = pil_new(304, CH)
    d.text((12, 6), "选株与记录", font=f20, fill=YEL)
    COL = {"empty": (228, 233, 229), "rec": (46, 158, 91), "dis": (205, 84, 84)}
    for i in range(PLANT_N):
        x1, y1, x2, y2 = _pcell(i)
        st = ("dis" if plant_rec[i]["diseases"] else "rec") if i in plant_rec else "empty"
        cur_cell = i == cur
        d.rectangle((x1, y1, x2, y2), fill=(31, 122, 140) if cur_cell else COL[st])
        if cur_cell:
            d.rectangle((x1, y1, x2, y2), outline=(20, 90, 110), width=3)
        tcol = INK if (st == "empty" and not cur_cell) else WHT
        lbl = str(i + 1)
        d.text((x1 + (PG_W - d.textlength(lbl, font=f20)) / 2, y1 + 5), lbl, font=f20, fill=tcol)
        if i in plant_rec:
            rr = plant_rec[i]
            sub = "%d/%d/%d" % (rr["green"], rr["half_ripened"], rr["fully_ripened"])
            d.text((x1 + (PG_W - d.textlength(sub, font=f14)) / 2, y1 + 31), sub, font=f14, fill=(235, 245, 238))
    y = 280
    d.text((12, y), "当前: 第 %d 株" % (cur + 1), font=f18, fill=CYAN); y += 26
    if cur in plant_rec:
        rr = plant_rec[cur]
        d.text((12, y), "青%d 半%d 红%d  ~%s" % (rr["green"], rr["half_ripened"], rr["fully_ripened"], gstr(rr["est_total"])), font=f16, fill=INK); y += 22
        if rr["diseases"]:
            d.text((12, y), "病害: " + "、".join(CN.get(n, n) for n in list(rr["diseases"])[:2]), font=f16, fill=RED)
    else:
        d.text((12, y), "尚未记录 (对准后点下方记录)", font=f16, fill=GRY)
    btn(d, PBTN_REC[0], PBTN_REC[1], PBTN_REC[2], PBTN_REC[3], "记录画面 → 第%d株" % (cur + 1), f18, (46, 158, 91), WHT)
    btn(d, PBTN_CLR[0], PBTN_CLR[1], PBTN_CLR[2], PBTN_CLR[3], "清除本株", f16, (205, 84, 84), WHT)
    K, g, h, r, tot = plant_summary()
    y = 458
    d.text((12, y), "全棚汇总  已记录 %d/%d 株" % (K, PLANT_N), font=f16, fill=YEL); y += 24
    d.text((12, y), "合计 青%d 半%d 红%d" % (g, h, r), font=f16, fill=INK); y += 24
    d.text((12, y), "总产 ~%s" % gstr(tot), font=f18, fill=GRN)
    d.text((10, CH - 22), "点格子切换 · 点记录存入 · [选株]收起", font=f14, fill=GRY)
    _pp.update(key=key, img=to_bgr(pil))
    return _pp["img"]


def hit(rects, x, y):
    for r in rects:
        if r[0] <= x <= r[2] and r[1] <= y <= r[3]:
            return r[4]
    return None


click = [None]


def on_mouse(ev, x, y, flags, param):
    if ev == cv2.EVENT_LBUTTONDOWN:
        click[0] = (x, y)


VOICE_TRIGGER = "/userdata/voice/voice_trigger"
VOICE_STATUS = "/userdata/voice/voice_status.json"
_VOICE = {"state": "idle", "q": "", "a": "", "ts": 0}
_PUSH = {"anim_start": 0, "result_ts": 0, "result": None}  # None/idle, "sending", "ok", "fail"
_VST = {"loading": ("正在载入语音模型…", (180, 210, 230)), "listening": ("正在倾听", (100, 200, 255)),
        "thinking": ("正在使用本地模型思考", (255, 180, 60)), "speaking": ("正在回答", (80, 230, 130)),
        "error": ("语音异常", (255, 120, 120))}
_vov = {"key": None, "img": None, "mask": None}


def is_voice_active():
    return _VOICE.get("state", "idle") in ("loading", "listening", "thinking", "speaking")


def read_voice_status():
    try:
        with open(VOICE_STATUS) as f:
            _VOICE.update(json.load(f))
    except Exception:
        pass


def trigger_voice():                          # 空内容=麦克风模式; daemon 监听此文件
    try:
        open(VOICE_TRIGGER, "w").close()
    except OSError:
        pass


def trigger_push():
    """手动推送温室报告到微信（后台线程，不阻塞UI）"""
    if _PUSH["result"] == "sending":
        return
    _PUSH["anim_start"] = time.time()
    _PUSH["result"] = "sending"
    def _do():
        try:
            r = subprocess.run(["python3", "/userdata/voice/daily_report.py"],
                               capture_output=True, text=True, timeout=30)
            _PUSH["result"] = "ok" if r.returncode == 0 else "fail"
        except Exception:
            _PUSH["result"] = "fail"
        _PUSH["result_ts"] = time.time()
    threading.Thread(target=_do, daemon=True).start()


def draw_bell_icon(canvas, cx, cy, scale=1.0, color=None):
    """🔔 造型铃铛，PIL 绘制（反锯齿）"""
    if color is None:
        color = (72, 180, 220)
    rgb = (color[2], color[1], color[0])
    s = scale
    w, h = int(24 * s), int(28 * s)
    pil = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(pil)
    mx, my = w // 2, h // 2
    # 顶部圆拱
    d.ellipse((mx - 6*s, 0, mx + 6*s, 12*s), fill=rgb)
    # 主体梯形（上窄下宽）
    d.polygon([(mx - 5*s, 5*s), (mx - 9*s, 16*s), (mx + 9*s, 16*s), (mx + 5*s, 5*s)], fill=rgb)
    # 底部横条
    d.rectangle((mx - 9*s, 16*s, mx + 9*s, 18*s), fill=rgb)
    # 铃舌（底部小球）
    d.ellipse((mx - 2.5*s, 19*s, mx + 2.5*s, 24*s), fill=rgb)
    # 贴到 canvas
    arr = np.array(pil)  # RGBA
    x0, y0 = int(cx - w / 2), int(cy - h / 2 + 2)
    x1, y1 = x0 + w, y0 + h
    if x0 < 0: arr = arr[:, -x0:]; x0 = 0
    if y0 < 0: arr = arr[-y0:, :]; y0 = 0
    if x1 > canvas.shape[1]: arr = arr[:, :canvas.shape[1] - x0]; x1 = canvas.shape[1]
    if y1 > canvas.shape[0]: arr = arr[:canvas.shape[0] - y0, :]; y1 = canvas.shape[0]
    roi = canvas[y0:y1, x0:x1]
    alpha = arr[:, :, 3:4].astype(np.float32) / 255.0
    blended = arr[:, :, :3] * alpha + roi * (1 - alpha)
    canvas[y0:y1, x0:x1] = blended.astype(np.uint8)


TOAST_FONT = None

def draw_push_toast(canvas, cx, top_y, text, bg_color, alpha=1.0):
    """铃铛上方弹出提示小框"""
    global TOAST_FONT
    if TOAST_FONT is None:
        try:
            TOAST_FONT = ImageFont.truetype(F, 16)
        except Exception:
            TOAST_FONT = ImageFont.load_default()
    rgb_bg = (bg_color[2], bg_color[1], bg_color[0])
    d = ImageDraw.Draw  # for measuring text; we use pil_new style

    # 测量文字大小
    test_img = Image.new("RGBA", (1, 1))
    td = ImageDraw.Draw(test_img)
    tw = td.textlength(text, font=TOAST_FONT)
    fh = TOAST_FONT.size
    pad_x, pad_y = 10, 5
    bw, bh = int(tw + pad_x * 2), int(fh + pad_y * 2)

    pil = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
    dd = ImageDraw.Draw(pil)
    # 圆角背景
    dd.rounded_rectangle((0, 0, bw, bh), radius=6, fill=rgb_bg + (int(220 * alpha),))
    # 文字
    dd.text((pad_x, pad_y), text, font=TOAST_FONT, fill=(255, 255, 255, int(255 * alpha)))

    arr = np.array(pil)
    x0, y0 = int(cx - bw / 2), int(top_y)
    x1, y1 = x0 + bw, y0 + bh
    if x0 < 0: arr = arr[:, -x0:]; x0 = 0
    if y0 < 0: arr = arr[-y0:, :]; y0 = 0
    if x1 > canvas.shape[1]: arr = arr[:, :canvas.shape[1] - x0]; x1 = canvas.shape[1]
    if y1 > canvas.shape[0]: arr = arr[:canvas.shape[0] - y0, :]; y1 = canvas.shape[0]
    roi = canvas[y0:y1, x0:x1]
    alpha_ch = arr[:, :, 3:4].astype(np.float32) / 255.0
    blended = arr[:, :, :3] * alpha_ch + roi * (1 - alpha_ch)
    canvas[y0:y1, x0:x1] = blended.astype(np.uint8)


def draw_voice_overlay(canvas):
    st = _VOICE.get("state", "idle")
    active = st in ("loading", "listening", "thinking", "speaking")
    q = _VOICE.get("q", "") or ""
    a = _VOICE.get("a", "") or ""
    recent = not active and a and (time.time() - _VOICE.get("ts", 0) < 5)
    if not active and not recent:
        return
    CWw, CHh = canvas.shape[1], canvas.shape[0]
    tick = time.time()
    dark = canvas.astype(np.float32) * 0.08
    canvas[:] = dark.astype(np.uint8)
    pil = Image.new("RGB", (CWw, CHh), (0, 0, 0))
    d = ImageDraw.Draw(pil)
    # Phase title
    title, col = _VST.get(st, ("语音助手", WHT))
    tw = d.textlength(title, font=f26)
    d.text(((CWw - tw) // 2, CHh // 2 - 76), title, font=f26, fill=col)
    # Phase dots
    phase_idx = {"listening": 1, "thinking": 2, "speaking": 3, "loading": 0}.get(st, 0)
    dots = ["● ○ ○ ○", "○ ● ○ ○", "○ ○ ● ○", "○ ○ ○ ●"][phase_idx]
    dtw = d.textlength(dots, font=f20)
    d.text(((CWw - dtw) // 2, CHh // 2 - 36), dots, font=f20,
           fill=(col[0]//2, col[1]//2, col[2]//2))
    # Animated waveform bars
    nbars = 52
    bar_w = max(3, CWw // (nbars * 2 + 2))
    gap = bar_w + 1
    total_w = nbars * gap
    start_x = (CWw - total_w) // 2
    base_y = CHh // 2 + 24
    for i in range(nbars):
        bx = start_x + i * gap
        if active:
            phase = tick * 3.8 + i * 0.25
            h_base = 50 * (0.5 + 0.5 * math.sin(phase))
            h_quick = 30 * math.sin(tick * 8.5 + i * 0.5) * math.cos(tick * 1.4)
            h = max(3, min(140, abs(h_base + h_quick)))
        else:
            h = 6
        x2, y1, y2 = bx + bar_w, int(base_y - h), int(base_y + h)
        d.rectangle((bx, y1, x2, y2), fill=col)
    # Center glow
    if active:
        pulse = 0.55 + 0.22 * math.sin(tick * 2.5)
        glow_r = int(20 + 14 * math.sin(tick * 3.3))
        glow_alpha = int(35 + 28 * pulse)
        glow_col = tuple(max(0, min(255, c * glow_alpha // 100)) for c in col)
        d.ellipse((CWw//2 - glow_r, base_y - glow_r, CWw//2 + glow_r, base_y + glow_r), fill=glow_col)
    # Question
    if q:
        qdisp = q[:50] + "…" if len(q) > 50 else q
        d.text((24, CHh // 2 + 96), "Q: " + qdisp, font=f20, fill=(200, 215, 210))
    # Answer — simple multi-line, no forced wrapping, no scrolling
    if a and (st == "speaking" or (st == "idle" and recent)):
        ay = CHh // 2 + 126
        max_w = CWw - 48
        for li, raw_line in enumerate(a.split('\n')):
            # only truncate if line exceeds screen width, keep natural breaks
            if d.textlength(raw_line, font=f18) > max_w:
                # trim to fit + ellipsis
                line = raw_line
                while d.textlength(line + "…", font=f18) > max_w and len(line) > 1:
                    line = line[:-1]
                line += "…"
            else:
                line = raw_line
            d.text((24, ay + li * 30), line, font=f18, fill=(170, 235, 180))
    # Bottom hint
    hint_map = {"listening": "请对着麦克风说话…", "thinking": "本地AI模型正在推理",
                "speaking": "正在语音播报", "loading": "模型加载中…"}
    hint = hint_map.get(st, "")
    hints_alpha = 0.55 + 0.25 * math.sin(tick * 2.0)
    if hint:
        htw = d.textlength(hint, font=f18)
        hint_col = (int(190 * hints_alpha), int(210 * hints_alpha), int(230 * hints_alpha))
        d.text(((CWw - htw) // 2, CHh - 72), hint, font=f18, fill=hint_col)
    overlay = to_bgr(pil)
    cv2.addWeighted(canvas, 0.55, overlay, 0.45, 0, dst=canvas)


SPEAKER = "crop_spk"                           # /etc/asound.conf 双声道上混设备, 修codec单声道2倍速变尖
VOLUME_FILE = "/userdata/voice/volume"        # 与语音daemon共享的单一音量来源(0-100)
VOL = [75]
_DAC_MAX = 360                                # UI 100% -> DAC Digital 360(再高失真); 实测50-78%为常用区


def _load_vol():
    try:
        with open(VOLUME_FILE) as f:
            VOL[0] = max(0, min(100, int(float(f.read().strip()))))
    except (OSError, ValueError):
        pass


def _save_vol():
    try:
        with open(VOLUME_FILE, "w") as f:
            f.write(str(VOL[0]))
    except OSError:
        pass


def apply_volume():                           # 板载codec无Master且每次播放结束DAC复位为0, 故每次aplay前重设
    dac = int(VOL[0] / 100.0 * _DAC_MAX)
    os.system("amixer -c0 sset 'DAC Digital' %d sset 'Power Amplifier' On sset 'Speaker' on >/dev/null 2>&1" % dac)


ALERT_DIR = "/userdata/voice/alerts"
ALERT_COOLDOWN = 90                           # 同病种语音告警冷却(s), 防反复刷
_lastalert = {}
_NO_PLAY = bool(os.environ.get("VOICE_NO_PLAY"))


def disease_alert(sm):                        # 检测到病害->秒播预缓存语音(非阻塞), 一次只播一个
    now = time.time()
    for nm in DISEASE_NAMES:
        if sm.get(nm, 0) <= 0 or now - _lastalert.get(nm, 0) < ALERT_COOLDOWN:
            continue
        wav = os.path.join(ALERT_DIR, nm + ".wav")
        if not os.path.exists(wav):
            continue
        _lastalert[nm] = now
        if not _NO_PLAY:
            apply_volume()
            try:
                subprocess.Popen(["aplay", "-D", SPEAKER, wav],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except OSError:
                pass
        return nm
    return None


def _logdir():
    for d in ("/userdata", "/run/media/mmcblk1p1"):   # 优先 eMMC(可靠), TF卡曾损坏只读退备选
        if os.path.isdir(d) and os.access(d, os.W_OK):
            try:
                t = os.path.join(d, ".wtest")
                open(t, "w").close(); os.remove(t)   # 实写验证(防TF ro/损坏假可写)
                return d
            except OSError:
                continue
    return "."


LOGDIR = _logdir()
CSVPATH = os.path.join(LOGDIR, "crop_log.csv")
CAPDIR = os.path.join(LOGDIR, "captures")
CSV_COLS = ["time", "green", "half_ripened", "fully_ripened", "fruit_total",
            "est_total_g", "est_ripe_g", "f7d_g"] + DISEASE_NAMES + ["disease_total"]
LOG_SEC, CAP_COOLDOWN = 30, 60
MAX_CAPTURES = 500     # 抓拍保留上限, 超出删最旧(按mtime), 防止写满 TF卡/eMMC; 500张约50-150MB
_lastcap = {}


def _prune_captures():
    try:
        fs = [os.path.join(CAPDIR, f) for f in os.listdir(CAPDIR) if f.endswith(".jpg")]
    except OSError:
        return
    if len(fs) <= MAX_CAPTURES:
        return
    fs.sort(key=os.path.getmtime)            # 文件名前缀是病种名, 排序≠时序, 必须按mtime
    for f in fs[:len(fs) - MAX_CAPTURES]:
        try:
            os.remove(f)
        except OSError:
            pass


_csv_checked = [False]


def _ensure_csv_schema():           # 旧CSV缺f7d_g列时就地迁移, 防新行错列
    if _csv_checked[0]:
        return
    _csv_checked[0] = True
    if not os.path.exists(CSVPATH):
        return
    try:
        with open(CSVPATH, newline="") as f:
            hdr = next(csv.reader(f), None)
        if hdr == CSV_COLS:
            return
        with open(CSVPATH, newline="") as f:
            old = list(csv.DictReader(f))
        tmp = CSVPATH + ".mig"
        with open(tmp, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=CSV_COLS, extrasaction="ignore")
            w.writeheader()
            for r in old:
                w.writerow({k: r.get(k, "") for k in CSV_COLS})
        os.replace(tmp, CSVPATH)
    except OSError:
        pass


def log_csv(sm, areas=None, f7=None):
    _ensure_csv_schema()
    g, h, r = sm.get("green", 0), sm.get("half_ripened", 0), sm.get("fully_ripened", 0)
    _, wt_t, wt_r = estimate_yield(sm, areas)
    wt_t, wt_r = round(wt_t, 1), round(wt_r, 1)
    f7v = round(f7, 1) if f7 is not None else ""
    dv = [sm.get(nm, 0) for nm in DISEASE_NAMES]
    row = [datetime.now().strftime("%Y-%m-%d %H:%M:%S"), g, h, r, g+h+r, wt_t, wt_r, f7v] + dv + [sum(dv)]
    new = not os.path.exists(CSVPATH)
    try:
        with open(CSVPATH, "a", newline="") as f:
            w = csv.writer(f)
            if new:
                w.writerow(CSV_COLS)
            w.writerow(row)
    except OSError:
        pass


def capture_disease(canvas, sm):    # 文件名无冒号: TF 卡是 vfat
    now = time.time()
    wrote = False
    for nm in DISEASE_NAMES:
        if sm.get(nm, 0) > 0 and now - _lastcap.get(nm, 0) >= CAP_COOLDOWN:
            fn = os.path.join(CAPDIR, "%s_%s.jpg" % (nm, datetime.now().strftime("%Y%m%d_%H%M%S")))
            try:
                cv2.imwrite(fn, canvas)
                _lastcap[nm] = now
                wrote = True
            except OSError:
                pass
    if wrote:
        _prune_captures()


def main():
    refresh_qr()
    _load_vol()
    apply_volume()
    cap = cv2.VideoCapture(DEV)
    os.system("v4l2-ctl -d %s -c auto_exposure=3 -c gain=32 -c brightness=0 -c contrast=38 -c saturation=53 2>/dev/null" % DEV)
    pool = rknnPoolExecutor(rknnModel="./rknnModel/best.rknn", TPEs=8, func=myFunc)
    if cap.isOpened():
        for _ in range(9):
            ret, frame = cap.read()
            if not ret:
                cap.release(); del pool; return
            frame = cv2.flip(frame, -1)
            pool.put(frame)

    win = "output_style_full_screen"
    cv2.namedWindow(win, cv2.WINDOW_NORMAL)
    cv2.setWindowProperty(win, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
    cv2.setMouseCallback(win, on_mouse)

    adjust_open = False
    plant_open = False
    current_plant = 0
    mode = "both"
    hist = deque(maxlen=12)
    canvas = np.zeros((CH, CW, 3), np.uint8)
    frames, loopTime, running = 0, time.time(), True
    last_log = time.time()
    try:
        os.makedirs(CAPDIR, exist_ok=True)
    except OSError:
        pass
    _prune_captures()
    load_plants_json()                        # 启动从磁盘恢复, 断电不丢
    if not plant_rec:
        write_plants_json(current_plant)      # 首次运行写空结构, 让 twin 立刻有数据
    while cap.isOpened() and running:
        frames += 1
        ret, frame = cap.read()
        if not ret:
            break
        frame = apply_rgb(frame)
        frame = cv2.flip(frame, -1)
        pool.put(frame)
        res, flag = pool.get()
        if not flag:
            break
        img, counts, area_sum = res
        hist.append((counts, area_sum))
        agg, agg_a = {}, {}
        for c, a in hist:
            for k, v in c.items():
                agg[k] = agg.get(k, 0) + v
            for k, v in a.items():
                agg_a[k] = agg_a.get(k, 0.0) + v
        n = len(hist)
        sm = {k: int(v/n + 0.5) for k, v in agg.items()}
        avg_area = {k: agg_a[k]/agg[k] for k in agg if agg[k] > 0 and k in agg_a}   # 每果平均框面积

        canvas[0:CAMH, 0:CAMW] = cv2.resize(img, (CAMW, CAMH))
        canvas[BARY:CH, 0:CAMW] = bottombar(mode)
        if adjust_open:
            canvas[0:CH, COLX:CW] = sidebar_adjust()
        elif plant_open:
            canvas[0:CH, COLX:CW] = plant_panel(current_plant)
        else:
            canvas[0:CH, COLX:CW] = sidebar_info(sm, avg_area, mode, current_plant)
        if frames % 8 == 0:
            read_voice_status()
        if frames % 150 == 0:        # 隧道URL可能延迟就绪/重连后变化, 周期刷新二维码
            refresh_qr()
        draw_voice_overlay(canvas)

        # 右下角推送铃铛（🔔 造型 + 动画反馈）
        bx, by, bx2, by2 = BTN_PUSH
        bcx, bcy = (bx + bx2) // 2, (by + by2) // 2

        push_now = time.time()
        push_elapsed = push_now - _PUSH.get("anim_start", 0)
        push_result = _PUSH.get("result", None)
        result_elapsed = push_now - _PUSH.get("result_ts", 0)

        # 铃铛弹跳缩放
        if push_result == "sending" and push_elapsed < 0.7:
            bounce = 1.0 + 0.25 * math.sin(push_elapsed * 22) * math.exp(-push_elapsed * 5)
        elif result_elapsed < 0.35:
            bounce = 1.0 + 0.18 * math.sin(result_elapsed * 18) * math.exp(-result_elapsed * 8)
        else:
            bounce = 1.0

        # 铃铛颜色
        if push_result == "sending":
            bell_c = (90, 210, 255)     # 亮金
        elif push_result == "ok":
            bell_c = (70, 210, 110)     # 绿色
        elif push_result == "fail":
            bell_c = (120, 100, 220)    # 红色
        else:
            bell_c = (72, 180, 220)     # 默认金

        draw_bell_icon(canvas, bcx, bcy, bounce, bell_c)

        # 铃铛上方 toast
        if push_result == "sending" and push_elapsed > 0.3:
            draw_push_toast(canvas, bcx, by - 36, "推送中…", (200, 160, 60), 1.0)
        elif push_result == "ok" and result_elapsed < 2.0:
            a = 1.0 if result_elapsed < 1.5 else max(0, (2.0 - result_elapsed) / 0.5)
            draw_push_toast(canvas, bcx, by - 36, "✓ 推送成功", (55, 185, 90), a)
        elif push_result == "fail" and result_elapsed < 2.0:
            a = 1.0 if result_elapsed < 1.5 else max(0, (2.0 - result_elapsed) / 0.5)
            draw_push_toast(canvas, bcx, by - 36, "✗ 推送失败", (200, 80, 80), a)

        if click[0] is not None:
            cx, cy = click[0]; click[0] = None
            if BTN_MODE[0] <= cx <= BTN_MODE[2] and BTN_MODE[1] <= cy <= BTN_MODE[3]:
                mode = DETECT_MODES[(DETECT_MODES.index(mode) + 1) % len(DETECT_MODES)]
                set_detect_mode(mode)
            elif BTN_PLANT[0] <= cx <= BTN_PLANT[2] and BTN_PLANT[1] <= cy <= BTN_PLANT[3]:
                plant_open = not plant_open
                if plant_open:
                    adjust_open = False
            elif BTN_ADJ[0] <= cx <= BTN_ADJ[2] and BTN_ADJ[1] <= cy <= BTN_ADJ[3]:
                adjust_open = not adjust_open
                if adjust_open:
                    plant_open = False
            elif BTN_VOICE[0] <= cx <= BTN_VOICE[2] and BTN_VOICE[1] <= cy <= BTN_VOICE[3]:
                trigger_voice()
            elif BTN_QUIT[0] <= cx <= BTN_QUIT[2] and BTN_QUIT[1] <= cy <= BTN_QUIT[3]:
                running = False
            elif BTN_PUSH[0] <= cx <= BTN_PUSH[2] and BTN_PUSH[1] <= cy <= BTN_PUSH[3]:
                trigger_push()
            elif plant_open:
                act = hit(plant_rects(), cx, cy)
                if act:
                    if act[0] == "plant":
                        current_plant = act[1]
                    elif act[0] == "record":
                        record_plant(current_plant, sm, avg_area)
                    elif act[0] == "clear":
                        plant_rec.pop(current_plant, None)
                    write_plants_json(current_plant)   # 选株/记录/清除即同步给数字孪生
            elif adjust_open:
                act = hit(adj_rects(), cx, cy)
                if act:
                    if act[0] == "toggle_auto":
                        set_auto(not auto_exp[0])
                    elif act[1] == "volume":
                        VOL[0] = max(0, min(100, VOL[0] + (5 if act[0] == "inc" else -5)))
                        _save_vol(); apply_volume()
                    elif act[1].startswith("rgb_"):
                        ch = act[1][4:]
                        v, lo, hi, st = RGB[ch]
                        RGB[ch][0] = max(lo, min(hi, v + (st if act[0] == "inc" else -st)))
                    else:
                        k = act[1]
                        if k == "exposure_time_absolute" and auto_exp[0]:
                            set_auto(False)
                        v, lo, hi, st = CTRL[k]
                        CTRL[k][0] = max(lo, min(hi, v + (st if act[0] == "inc" else -st)))
                        setc(k)

        cv2.imshow(win, canvas)
        capture_disease(canvas, sm)
        disease_alert(sm)
        if mode != "disease" and time.time() - last_log >= LOG_SEC:   # 仅病叶模式无果实, 跳过产量日志防污染预测历史
            fv, fdays = forecast_7d(sm)
            _FC.update(v=fv, days=fdays)
            log_csv(sm, avg_area, fv); last_log = time.time()
        if frames % 30 == 0:
            cv2.imwrite("./live_raw.jpg", frame)
            cv2.imwrite("./live_out.jpg", canvas)
            cv2.imwrite("./live_cam.jpg", canvas[0:CAMH, 0:CAMW])   # 纯摄像头+检测框(无侧栏/按钮), 供网页大屏
            print("fps:", round(30 / (time.time() - loopTime), 1), flush=True)
            loopTime = time.time()
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cap.release(); cv2.destroyAllWindows(); pool.release()


if __name__ == "__main__":
    main()
