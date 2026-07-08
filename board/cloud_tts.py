"""云端TTS: Microsoft Edge TTS (免费, 中文好) → 本地 Piper 兜底"""
import os, subprocess, tempfile

VOICE = "zh-CN-XiaoxiaoNeural"  # 女声, 自然清晰. 可选: zh-CN-YunxiNeural(男声)
SPEED = "+0%"                    # 语速: -20% 更慢, +20% 更快


def synthesize(text, out_wav, voice=None, speed=None):
    """调用 edge-tts 生成语音, mp3→wav via sox。成功返 True, 失败返 False。"""
    voice = voice or VOICE
    speed = speed or SPEED
    try:
        # 临时 mp3
        fd, tmp_mp3 = tempfile.mkstemp(suffix=".mp3", prefix="edge_")
        os.close(fd)
        subprocess.run(
            ["edge-tts", "--voice", voice, "--rate", speed,
             "--text", text, "--write-media", tmp_mp3],
            check=True, timeout=30,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        # mp3 → wav
        subprocess.run(
            ["sox", tmp_mp3, "-t", "wav", "-r", "16000", "-c", "1", "-b", "16", out_wav],
            check=True, timeout=15,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        return True
    except Exception:
        return False
    finally:
        try:
            os.remove(tmp_mp3)
        except OSError:
            pass


def is_available():
    """检查 edge-tts 是否可用"""
    try:
        r = subprocess.run(["edge-tts", "--version"], capture_output=True, timeout=5)
        return r.returncode == 0
    except Exception:
        return False


if __name__ == "__main__":
    print("available:", is_available())
    if is_available():
        ok = synthesize("你好，云端语音合成测试成功。", "/tmp/_cloud_tts_test.wav")
        print("synth:", ok)
