import sys, time, wave
import numpy as np
sys.path.insert(0, "/userdata/voice/libs")
sys.path.insert(0, "/userdata/voice")
import sherpa_onnx

V = "/userdata/voice"
TXT = "你好，当前温室温度二十四摄氏度，湿度百分之六十五，未发现病害。"


def save(path, samples, sr):
    pcm = (np.clip(np.asarray(samples, np.float32), -1, 1) * 32767).astype(np.int16)
    with wave.open(path, "w") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes(pcm.tobytes())


def tts_of(d, model):
    cfg = sherpa_onnx.OfflineTtsConfig(
        model=sherpa_onnx.OfflineTtsModelConfig(
            vits=sherpa_onnx.OfflineTtsVitsModelConfig(
                model=f"{d}/{model}", lexicon=f"{d}/lexicon.txt",
                tokens=f"{d}/tokens.txt", dict_dir=f"{d}/dict"),
            num_threads=4, provider="cpu"),
        rule_fsts=f"{d}/date.fst,{d}/number.fst,{d}/phone.fst", max_num_sentences=1)
    return sherpa_onnx.OfflineTts(cfg)


def run(tag, tts, sid, speed):
    t = time.time(); a = tts.generate(TXT, sid=sid, speed=speed)
    dur = len(a.samples) / a.sample_rate
    save(f"{V}/cand_{tag}.wav", a.samples, a.sample_rate)
    print("%-22s gen=%5.1fs dur=%4.1fs RTF=%.2f sr=%d" % (tag, time.time() - t, dur, (time.time() - t) / dur, a.sample_rate), flush=True)


ft = tts_of(f"{V}/models/fanchen", "vits-zh-hf-fanchen-C.onnx")
run("fanchen_s0_baseline", ft, 0, 1.0)            # 当前音色(参照)
for sid in [21, 47, 66, 99, 132, 165]:
    run("fanchen_s%d_sp90" % sid, ft, sid, 0.9)
del ft

mt = tts_of(f"{V}/models/melo-tts", "model.onnx")
run("melo_s0_sp90", mt, 0, 0.9)
del mt
print("DONE", flush=True)
