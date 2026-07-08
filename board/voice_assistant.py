import os, sys, time, wave, argparse, subprocess, json, csv, threading, queue, re
import numpy as np

sys.path.insert(0, "/userdata/voice/libs")
sys.path.insert(0, "/userdata/voice")
sys.path.insert(0, "/userdata/llm")
import sherpa_onnx
from rkllm_chat import RKLLMRunner
import cloud_llm
import cloud_tts
import agent_tools


VOICE = "/userdata/voice"
ASR_DIR = f"{VOICE}/models/sensevoice"
TTS_DIR = f"{VOICE}/models/fanchen"
LLM_MODEL = "/userdata/llm/models/qwen2.5-0.5b-rv1126b-w4a16.rkllm"
MIC = "plughw:1,0"
SPEAKER = "crop_spk"                         # /etc/asound.conf: plug->hw:0,0 强制双声道(codec I2S配双声道,单声道会2倍速变尖)
SENSORS = "/userdata/sensors.json"
CSVLOG = "/userdata/crop_log.csv"
VOLUME_FILE = f"{VOICE}/volume"              # 与检测UI共享的单一音量来源(0-100)
_DAC_MAX = 360


def apply_volume():                          # 板载codec无Master且每次播放结束DAC复位为0, 每次aplay前按存档音量重设
    try:
        with open(VOLUME_FILE) as f:
            vol = max(0, min(100, int(float(f.read().strip()))))
    except (OSError, ValueError):
        vol = 75
    dac = int(vol / 100.0 * _DAC_MAX)
    os.system("amixer -c0 sset 'DAC Digital' %d sset 'Power Amplifier' On sset 'Speaker' on >/dev/null 2>&1" % dac)

DIS_CN = {"bacterial_spot": "细菌性斑点", "early_blight": "早疫病", "late_blight": "晚疫病",
          "leaf_mold": "叶霉病", "leaf_miner": "潜叶蝇", "mosaic_virus": "花叶病毒",
          "septoria": "斑枯病", "spider_mites": "红蜘蛛", "yellow_leaf_curl_virus": "黄化曲叶病毒"}

SYS_PROMPT = (
    "你是番茄温室AI助手，在福建莆田的温室里工作。你不仅可以回答问题，还可以控制温室设备。\n"
    "【环境】=温室内传感器读数（温度/湿度/CO2/光照/土壤湿度）。\n"
    "【选株】=8株番茄逐株手动记录（青果/半熟/红果/病害/估产），未记录=尚未检测。\n"
    "【室外天气】=互联网获取的当地真实天气（当前+未来3天预报）。\n"
    "【果实/产量/病害】=摄像头AI实时检测的汇总结果。\n"
    "回答规则：1.问某株时引用该株的具体数据 2.引用具体数字 3.室内外对比给建议 "
    "4.未来有雨提醒防病 5.用一两句话简短回答 6.不知道就说不知道，不编造 "
    "7.当用户要求开/关风扇或水泵时，先调用工具执行，然后告知结果。"
    "\n"
    + agent_tools.TOOL_PROMPT
)


def clean_answer(s):                         # 0.5B 常在"答："后续写下一轮"问："->截断
    for cut in ("\n问：", "\n\n问", "\n答：", "问：", "答："):
        i = s.find(cut)
        if i > 0:
            s = s[:i]
    return s.strip()


def gstr(x):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return "—"
    return "%.2f公斤" % (x / 1000.0) if x >= 1000 else "%d克" % round(x)


def _num(v, cast=float, default=None):
    try:
        return cast(v)
    except (TypeError, ValueError):
        return default


def crop_context():                          # 把传感器+最近检测拼成给LLM的接地上下文
    parts = []
    try:
        with open(SENSORS) as f:
            s = json.load(f)
        parts.append("环境：温度%.1f℃，湿度%.0f%%，CO2 %d ppm，光照%d lux"
                     % (s.get("temp", 0), s.get("rh", 0), s.get("co2", 0), s.get("lux", 0)))
    except Exception:
        pass
    try:
        with open(CSVLOG, newline="") as f:
            rows = list(csv.DictReader(f))
        if rows:
            r = rows[-1]
            g = _num(r.get("green"), int, 0); h = _num(r.get("half_ripened"), int, 0)
            ripe = _num(r.get("fully_ripened"), int, 0)
            parts.append("果实计数：青果%d个，半熟%d个，红果(可采收)%d个" % (g, h, ripe))
            parts.append("产量估算：预计总产%s，其中红果%s"
                         % (gstr(r.get("est_total_g")), gstr(r.get("est_ripe_g"))))
            f7 = _num(r.get("f7d_g"))
            if f7 is not None:
                parts.append("未来7天预计可采收：%s" % gstr(f7))
            dis = ["%s%d个" % (DIS_CN[k], _num(r.get(k), int, 0))
                   for k in DIS_CN if _num(r.get(k), int, 0) > 0]
            parts.append("病害：" + ("、".join(dis) if dis else "未发现异常"))
    except Exception:
        pass
    try:
        with open("/userdata/plants.json") as f:
            pdata = json.load(f)
        plants = pdata.get("plants", [])
        scanned = [p for p in plants if p.get("scanned")]
        cur = pdata.get("current", -1)
        parts.append("选株记录（%d/8株已记录，当前选中第%d株）：" % (len(scanned), cur + 1))
        for p in plants:
            pid = p["id"] + 1
            if p.get("scanned"):
                info = []
                fruit = []
                if p.get("green"): fruit.append("青%d" % p["green"])
                if p.get("half"): fruit.append("半熟%d" % p["half"])
                if p.get("ripe"): fruit.append("红%d" % p["ripe"])
                if fruit: info.append("、".join(fruit))
                if p.get("disease"): info.append(DIS_CN.get(p["disease"], p["disease"]))
                if p.get("est", 0) > 0: info.append("估产%s" % gstr(p["est"]))
                parts.append("  第%d株：%s" % (pid, "，".join(info) if info else "已记录（无异常）"))
            else:
                parts.append("  第%d株：未记录" % pid)
    except Exception:
        pass
    try:
        from weather import weather_summary
        ws = weather_summary()
        if ws:
            parts.append(ws)
    except Exception:
        pass
    return "\n".join(parts) if parts else "（暂无实时数据）"


def load_asr():
    return sherpa_onnx.OfflineRecognizer.from_sense_voice(
        model=f"{ASR_DIR}/model.int8.onnx", tokens=f"{ASR_DIR}/tokens.txt",
        num_threads=4, use_itn=True, language="zh",
    )


PIPER_DIR = f"{VOICE}/models/piper-medium"   # Piper huayan-medium: 相机负载下RTF~1.2(fanchen是8), 清晰自然


def load_tts():                              # Piper走espeak音素化(无rule_fsts), 数字/符号靠 norm_cn() 预归一化
    cfg = sherpa_onnx.OfflineTtsConfig(
        model=sherpa_onnx.OfflineTtsModelConfig(
            vits=sherpa_onnx.OfflineTtsVitsModelConfig(
                model=f"{PIPER_DIR}/model.onnx",
                tokens=f"{PIPER_DIR}/tokens.txt",
                data_dir=f"{PIPER_DIR}/espeak-ng-data",
            ), num_threads=4, provider="cpu",
        ),
        max_num_sentences=1,
    )
    return sherpa_onnx.OfflineTts(cfg)


def read_wav(path):
    with wave.open(path) as w:
        sr, n, ch = w.getframerate(), w.getnframes(), w.getnchannels()
        a = np.frombuffer(w.readframes(n), dtype=np.int16).astype(np.float32) / 32768.0
    if ch > 1:
        a = a.reshape(-1, ch).mean(axis=1)
    return a, sr


def save_wav(path, samples, sr):
    pcm = (np.clip(np.asarray(samples, np.float32), -1, 1) * 32767).astype(np.int16)
    with wave.open(path, "w") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes(pcm.tobytes())


def split_sentences(text):                   # 按句切, 太短的并入上一句, 避免碎播
    text = (text or "").strip()
    if not text:
        return []
    out, buf = [], ""
    for ch in text:
        buf += ch
        if ch in "。！？!?；;\n" and len(buf.strip()) >= 6:
            out.append(buf.strip()); buf = ""
    if buf.strip():
        if out and len(buf.strip()) < 6:
            out[-1] += buf.strip()
        else:
            out.append(buf.strip())
    return out


TTS_CFG = f"{VOICE}/tts.json"                # {"engine":"espeak|neural","espeak_speed":175,"espeak_pitch":42,"sid":N,"speed":0.9} 改这文件即生效


def tts_params():
    try:
        with open(TTS_CFG) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _int2cn(n):
    if n == 0:
        return "零"
    if n < 0:
        return "负" + _int2cn(-n)
    digs = "零一二三四五六七八九"

    def under1k(x):
        s = ""
        h, t, u = x // 100, (x // 10) % 10, x % 10
        if h:
            s += digs[h] + "百"
        if t:
            s += digs[t] + "十"
        elif h and u:
            s += "零"
        if u:
            s += digs[u]
        return s

    if n < 1000:
        r = under1k(n)
    elif n < 10000:
        hi, lo = n // 1000, n % 1000
        r = digs[hi] + "千" + (("零" if lo < 100 else "") + under1k(lo) if lo else "")
    elif n < 100000000:
        hi, lo = n // 10000, n % 10000
        r = _int2cn(hi) + "万" + (("零" if lo < 1000 else "") + (_int2cn(lo) if lo >= 1000 else under1k(lo)) if lo else "")
    else:
        return str(n)
    return r[1:] if r.startswith("一十") else r


def _num2cn(tok):
    if "." in tok:
        ip, fp = tok.split(".", 1)
        digs = "零一二三四五六七八九"
        return _int2cn(int(ip)) + "点" + "".join(digs[int(c)] for c in fp)
    return _int2cn(int(tok))


def norm_cn(text):                           # espeak读阿拉伯数字/符号会跳英文, 先转纯中文
    text = text.replace("℃", "摄氏度").replace("°C", "摄氏度").replace("°", "度")
    text = re.sub(r"(\d+(?:\.\d+)?)\s*%", lambda m: "百分之" + _num2cn(m.group(1)), text)
    text = re.sub(r"(\d+(?:\.\d+)?)", lambda m: _num2cn(m.group(1)), text)
    return text.replace("lux", "勒克斯").replace("PPM", "ppm")


def _speak_espeak(text, speaker, no_play, reply_path, cfg):
    sp = int(cfg.get("espeak_speed", 175))   # 字/分, 越大越快
    pit = int(cfg.get("espeak_pitch", 42))   # 0-99, 越低越沉稳
    gap = int(cfg.get("espeak_gap", 4))      # 词间停顿(10ms单位)
    try:
        subprocess.run(["espeak-ng", "-v", "cmn", "-s", str(sp), "-p", str(pit), "-g", str(gap),
                        norm_cn(text), "-w", reply_path], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.CalledProcessError):
        return reply_path
    if not no_play:
        apply_volume()
        try:
            subprocess.run(["aplay", "-D", speaker, "-q", reply_path],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            pass
    return reply_path



def speak(tts, text, speaker=SPEAKER, no_play=False, reply_path=f"{VOICE}/reply.wav",
          on_sentence=None):
    """普通话(edge-tts→Piper) 语音合成与播放"""
    # edge-tts 云端 TTS (微软免费, 中文好)
    if cloud_tts.is_available():
        try:
            ok = cloud_tts.synthesize(text, reply_path)
            if ok and os.path.getsize(reply_path) > 1000:
                if on_sentence:
                    on_sentence(0, 1)
                if not no_play:
                    apply_volume()
                    subprocess.run(["aplay", "-D", speaker, "-q", reply_path],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return reply_path
        except Exception:
            pass
    # 云端失败 → 本地兜底
    cfg = tts_params()
    if cfg.get("engine", "neural") == "espeak":
        ret = _speak_espeak(text, speaker, no_play, reply_path, cfg)
        return ret
    sents = split_sentences(norm_cn(text))   # Piper经espeak音素化, 数字/符号须先转中文
    if not sents:
        return reply_path
    sid, speed = int(cfg.get("sid", 0)), float(cfg.get("speed", 0.7))
    q, th = None, None
    if not no_play:
        q = queue.Queue()

        def player():
            while True:
                p = q.get()
                if p is None:
                    break
                try:
                    apply_volume()
                    subprocess.run(["aplay", "-D", speaker, "-q", p],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    os.remove(p)
                except OSError:
                    pass
        th = threading.Thread(target=player, daemon=True)
        th.start()
    all_samples, sr = [], 16000
    for i, s in enumerate(sents):
        if on_sentence:
            on_sentence(i, len(sents))
        audio = tts.generate(s, sid=sid, speed=speed)
        samp = np.asarray(audio.samples, np.float32)
        sr = audio.sample_rate
        all_samples.append(samp)
        if not no_play:
            p = os.path.join(VOICE, "_say_%d.wav" % i)
            save_wav(p, samp, sr)
            q.put(p)
    if not no_play:
        q.put(None); th.join()
    if reply_path and all_samples:
        save_wav(reply_path, np.concatenate(all_samples), sr)
    return reply_path


def record(seconds, out=f"{VOICE}/_in.wav"):
    subprocess.run(["arecord", "-D", pick_mic(), "-d", str(seconds), "-r", "16000",
                    "-f", "S16_LE", "-c", "1", out], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return read_wav(out)


VAD_MODEL = f"{VOICE}/models/vad/silero_vad.onnx"


def _list_capture():
    try:
        out = subprocess.check_output(["arecord", "-l"], text=True, stderr=subprocess.DEVNULL)
    except Exception:
        return []
    res = []
    for ln in out.splitlines():
        m = re.match(r"\s*card (\d+): \S+ \[([^\]]+)\]", ln)
        if m:
            res.append((int(m.group(1)), m.group(2)))
    return res


def pick_mic():                              # 动态选麦: 独立USB麦/耳麦优先 > 摄像头复合麦(实测死) > 板载(无物理麦); 后插的USB麦card号大优先
    cands = _list_capture()
    if not cands:
        return MIC

    def rank(c):
        n = c[1].lower()
        if "rockchip" in n or "rv1126" in n or "acodec" in n:
            return 0
        if "icspring" in n or "camera" in n:
            return 1
        return 2
    cands.sort(key=lambda c: (rank(c), c[0]), reverse=True)
    return "plughw:%d,0" % cands[0][0]


def _make_vad(sr=16000):
    cfg = sherpa_onnx.VadModelConfig()
    cfg.silero_vad.model = VAD_MODEL
    cfg.silero_vad.threshold = 0.5
    cfg.silero_vad.min_silence_duration = 0.6    # 说完静音0.6s即判定结束自动停
    cfg.silero_vad.min_speech_duration = 0.2
    cfg.silero_vad.max_speech_duration = 12.0
    cfg.silero_vad.window_size = 512
    cfg.sample_rate = sr
    return sherpa_onnx.VoiceActivityDetector(cfg, 30)


def record_vad(max_wait=10.0, sr=16000, on_speech=None):
    """流式录音+VAD端点检测: 等到有人说话才开始收, 静音自动停, 返回裁好的语音段。
    空数组=max_wait内没听到说话。取代固定盲录, 不再因时机错位录到空。"""
    dev = pick_mic()
    win = 512
    proc = subprocess.Popen(
        ["arecord", "-D", dev, "-f", "S16_LE", "-c", "1", "-r", str(sr), "-t", "raw", "-q"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    vad = _make_vad(sr)
    t0 = time.time()
    spoke = False
    buf = b""
    try:
        while True:
            data = proc.stdout.read(2048)
            if not data:
                break
            buf += data
            while len(buf) >= win * 2:
                frame = buf[:win * 2]; buf = buf[win * 2:]
                samp = np.frombuffer(frame, np.int16).astype(np.float32) / 32768.0
                vad.accept_waveform(samp)
                if vad.is_speech_detected() and not spoke:
                    spoke = True
                    if on_speech:
                        on_speech()
                while not vad.empty():
                    seg = np.array(vad.front.samples, dtype=np.float32)
                    vad.pop()
                    if len(seg) >= int(0.2 * sr):
                        return seg, sr
            now = time.time()
            if not spoke and now - t0 > max_wait:
                return np.zeros(0, np.float32), sr
            if now - t0 > 25:
                break
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=1)
        except Exception:
            pass
    return np.zeros(0, np.float32), sr


def asr_transcribe(asr, samples, sr):
    s = asr.create_stream()
    s.accept_waveform(sr, samples)
    asr.decode_stream(s)
    return s.result.text.strip()


def answer(q, llm, tts, play, speaker, no_tts):
    ctx = crop_context()
    print("【实时数据】\n" + ctx, flush=True)
    t = time.time()
    prompt = f"{SYS_PROMPT}\n【实时数据】\n{ctx}\n问：{q}\n答："

    ans, perf = _agent_chat(q, ctx, prompt, llm)

    tag = "云端" if perf.get("cloud") else "本地"
    tool_info = ""
    if perf.get("tools_called"):
        tool_info = " [调用了%d个工具]" % len(perf["tools_called"])
    print("回答(%s%.1fs)%s：%s" % (tag, time.time() - t, tool_info, ans), flush=True)
    if no_tts:
        return
    t = time.time()
    out = speak(tts, ans, speaker=speaker, no_play=not play)
    print("合成%s(TTS %.1fs)：%s" % ("+流式播放" if play else "", time.time() - t, out), flush=True)


def _agent_chat(q, ctx, prompt, llm):
    """Agent 对话: 支持工具调用, 最多 3 轮"""
    perf = {"tools_called": []}
    user_msg = f"【实时数据】\n{ctx}\n问：{q}\n答："

    for round_num in range(3):
        ans = None
        # ① 云端 LLM (GLM-4-Flash 支持原生 function calling)
        try:
            ans, extra = cloud_llm.chat(
                SYS_PROMPT, user_msg,
                tools=agent_tools.TOOLS if round_num == 0 else None)
            if ans:
                ans = clean_answer(ans)
                perf["cloud"] = True
                # 检查是否有 tool_calls
                tc = extra.get("tool_calls") if extra else None
                if tc:
                    for call in tc:
                        name = call.get("function", {}).get("name", "")
                        args = json.loads(call.get("function", {}).get("arguments", "{}"))
                        print(f"  [Agent] 调用工具: {name}({args})")
                        result = agent_tools.execute_tool(name, args)
                        print(f"  [Agent] 工具返回: {result[:100]}...")
                        perf["tools_called"].append(name)
                        user_msg += f"\n工具调用 {name} 返回：{result}\n请基于以上结果回答用户。"
                    ans = None  # 工具调用后需要再问一轮
                    continue
            if ans:
                break
        except Exception:
            pass

        # ② 本地 LLM (prompt 模式解析 <tool>...</tool>)
        if not ans:
            raw, rkllm_perf = llm.chat(prompt if round_num == 0 else
                                       prompt + "\n" + user_msg.split("\n")[-1])
            raw = clean_answer(raw)
            tool_call, clean = agent_tools.parse_local_tool(raw)
            if tool_call:
                name, args = tool_call
                print(f"  [Agent 本地] 调用工具: {name}({args})")
                result = agent_tools.execute_tool(name, args)
                print(f"  [Agent 本地] 工具返回: {result[:100]}...")
                perf["tools_called"].append(name)
                perf["local_tool"] = True
                prompt += f"\n工具调用 {name} 返回：{result}\n请基于以上结果用一两句话回答用户。"
                continue
            ans = clean
            perf["cloud"] = False

    if not ans:
        ans = "抱歉，我暂时无法处理这个请求。"
    return ans, perf


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wav", help="输入语音文件")
    ap.add_argument("--mic", type=int, default=0, metavar="SEC", help="麦克风录音秒数(单次)")
    ap.add_argument("--ask", help="直接文本提问(跳过ASR), 静音测试用")
    ap.add_argument("--loop", type=int, default=0, metavar="SEC", help="连续对话:每轮录音SEC秒, Ctrl-C退出")
    ap.add_argument("--play", action="store_true", help="合成后经喇叭播放")
    ap.add_argument("--speaker", default=SPEAKER, help="aplay 播放设备")
    ap.add_argument("--no-tts", action="store_true", help="只出文本不合成语音")
    args = ap.parse_args()

    need_asr = not args.ask                  # --ask 纯文本无需 ASR
    t0 = time.time()
    asr = load_asr() if need_asr else None
    tts = None if args.no_tts else load_tts()
    llm = RKLLMRunner(LLM_MODEL, max_new_tokens=128)
    print("[模型就绪 %.1fs]\n" % (time.time() - t0), flush=True)

    try:
        if args.ask:
            answer(args.ask, llm, tts, args.play, args.speaker, args.no_tts)
        elif args.loop:
            print("连续对话模式, Ctrl-C 退出\n", flush=True)
            while True:
                print("请说话 %ds ..." % args.loop, flush=True)
                samples, sr = record(args.loop)
                q = asr_transcribe(asr, samples, sr)
                print("识别：%s" % q, flush=True)
                if q:
                    answer(q, llm, tts, args.play, args.speaker, args.no_tts)
                print("", flush=True)
        else:
            if args.wav:
                samples, sr = read_wav(args.wav)
            else:
                sec = args.mic or 5
                print("录音 %ds ..." % sec, flush=True)
                samples, sr = record(sec)
            t = time.time()
            q = asr_transcribe(asr, samples, sr)
            print("识别(ASR %.1fs)：%s" % (time.time() - t, q), flush=True)
            if q:
                answer(q, llm, tts, args.play, args.speaker, args.no_tts)
            else:
                print("没听清，结束")
    except KeyboardInterrupt:
        print("\n退出")
    finally:
        llm.release()


if __name__ == "__main__":
    main()
