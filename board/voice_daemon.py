"""常驻语音助手守护进程 v2: Agent模式, 支持工具调用(控制风扇/水泵/查传感器)。

触发(由 main_camera_live 语音按钮或手动):
    touch /userdata/voice/voice_trigger            -> 麦克风录音提问
    echo '温室状态如何' > /userdata/voice/voice_trigger  -> 文本提问(跳过ASR, 静音测试用)

状态: /userdata/voice/voice_status.json {state,q,a,ts}
跑: LD_LIBRARY_PATH=/userdata/llm/lib python3 voice_daemon.py
"""
import os, sys, time, json, traceback, subprocess
sys.path.insert(0, "/userdata/voice")
sys.path.insert(0, "/userdata/voice/libs")
sys.path.insert(0, "/userdata/llm")
import voice_assistant as VA
import agent_tools
import cloud_llm

TRIGGER = "/userdata/voice/voice_trigger"
STATUS = "/userdata/voice/voice_status.json"
REPLY = "/userdata/voice/reply.wav"
REC_SEC = int(os.environ.get("VOICE_REC_SEC", "5"))
NO_PLAY = bool(os.environ.get("VOICE_NO_PLAY"))
MAX_AGENT_ROUNDS = 3


def set_status(state, q="", a="", **extra):
    try:
        tmp = STATUS + ".tmp"
        d = {"state": state, "q": q, "a": a, "ts": int(time.time())}
        d.update(extra)
        with open(tmp, "w") as f:
            json.dump(d, f, ensure_ascii=False)
        os.replace(tmp, STATUS)
    except OSError:
        pass


def agent_answer(q, llm):
    """Agent 对话: 支持工具调用, 最多3轮"""
    ctx = VA.crop_context()
    sys_prompt = VA.SYS_PROMPT
    user_msg = "【实时数据】\n%s\n问：%s\n答：" % (ctx, q)
    tools_called = []

    for round_num in range(MAX_AGENT_ROUNDS):
        ans = None
        is_cloud = False

        # ── ① 云端 LLM (带原生 function calling) ──
        try:
            ans, meta = cloud_llm.chat(
                sys_prompt, user_msg, max_tokens=256,
                tools=agent_tools.TOOLS if round_num == 0 else None)
            if meta.get("tool_calls"):
                # 执行工具调用
                for tc in meta["tool_calls"]:
                    fn = tc.get("function", {})
                    name = fn.get("name", "")
                    args = json.loads(fn.get("arguments", "{}"))
                    print("  [Agent] %s(%s)" % (name, args), flush=True)
                    result = agent_tools.execute_tool(name, args)
                    tools_called.append(name)
                    user_msg += "\n[工具 %s 返回]: %s" % (name, result)
                    user_msg += "\n请基于工具返回结果用一两句话回答用户。"
                    set_status("thinking", q, last_a,
                               tool_info="%s(%s)" % (name, list(args.values())[0] if args else ""))
                continue  # 工具调用后进入下一轮
            if ans:
                ans = VA.clean_answer(ans)
                is_cloud = True
                break
        except Exception as e:
            print("  [Agent] 云端失败: %s" % str(e)[:80], flush=True)

        # ── ② 本地 LLM (prompt模式解析 <tool>...</tool>) ──
        prompt = "%s\n%s" % (sys_prompt, user_msg)
        raw, _ = llm.chat(prompt)
        raw = VA.clean_answer(raw)
        tool_call, clean = agent_tools.parse_local_tool(raw)
        if tool_call:
            name, args = tool_call
            print("  [Agent本地] %s(%s)" % (name, args), flush=True)
            result = agent_tools.execute_tool(name, args)
            tools_called.append(name)
            user_msg += "\n[工具 %s 返回]: %s" % (name, result)
            user_msg += "\n请基于工具返回结果用一两句话回答用户。"
            set_status("thinking", q, last_a,
                       tool_info="%s(%s)" % (name, list(args.values())[0] if args else ""))
            continue
        ans = clean
        break

    if not ans:
        ans = "抱歉，我暂时无法处理这个请求。"
    return ans, tools_called, is_cloud


def main():
    print("[voice daemon] starting...", flush=True)
    set_status("loading")
    asr = VA.load_asr()
    tts = VA.load_tts()
    llm = VA.RKLLMRunner(VA.LLM_MODEL, max_new_tokens=128)
    set_status("idle")
    print("[voice daemon ready] rec=%ds no_play=%s" % (REC_SEC, NO_PLAY), flush=True)

    global last_a
    last_q = last_a = ""
    while True:
        if not os.path.exists(TRIGGER):
            time.sleep(0.2)
            continue
        try:
            text = open(TRIGGER).read().strip()
        except OSError:
            text = ""
        try:
            os.remove(TRIGGER)
        except OSError:
            pass
        try:
            if text:
                q = text
            else:
                set_status("listening", last_q, last_a)
                samples, sr = VA.record_vad()
                if len(samples) == 0:
                    set_status("idle", "(没听到声音)", last_a)
                    continue
                q = VA.asr_transcribe(asr, samples, sr)
            if not q:
                set_status("idle", "(没听清)", last_a)
                continue
            last_q = q
            set_status("thinking", q, last_a)

            ans, tools, is_cloud = agent_answer(q, llm)
            last_a = ans

            tag = "cloud" if is_cloud else "local"
            tool_str = (" [tools:%s]" % ",".join(tools)) if tools else ""
            print("Q:%s | A(%s)%s: %s" % (q, tag, tool_str, ans), flush=True)

            sents = VA.split_sentences(VA.norm_cn(ans))
            if not sents:
                sents = [ans]
            set_status("speaking", q, ans, a_sents=sents, a_idx=0, a_total=len(sents))

            def on_sentence(idx, total):
                set_status("speaking", q, ans, a_sents=sents, a_idx=idx, a_total=total)

            VA.speak(tts, ans, speaker=VA.SPEAKER, no_play=NO_PLAY, reply_path=REPLY,
                     on_sentence=on_sentence)
            set_status("idle", q, ans)
        except Exception as e:
            traceback.print_exc()
            set_status("error", last_q, str(e)[:60])


if __name__ == "__main__":
    main()
