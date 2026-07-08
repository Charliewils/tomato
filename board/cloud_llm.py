"""云端LLM模块: 多后端 + 超时快速失败 → 本地兜底"""
import json, time, urllib.request, urllib.error

CONFIG_PATH = "/userdata/voice/cloud_config.json"
TIMEOUT = 15  # 云端超时秒数, 超过即退本地


def _load_cfg():
    try:
        with open(CONFIG_PATH) as f:
            return json.load(f)
    except Exception:
        return {}


def _chat_openai_compat(endpoint, api_key, model, sys_prompt, user_prompt,
                        max_tokens=256, chat_path="/v1/chat/completions", tools=None):
    """通用 OpenAI 兼容接口。支持 function calling。"""
    url = f"{endpoint.rstrip('/')}{chat_path}"
    msgs = [
        {"role": "system", "content": sys_prompt},
        {"role": "user", "content": user_prompt},
    ]
    body = {
        "model": model,
        "messages": msgs,
        "max_tokens": max_tokens,
        "temperature": 0.7,
    }
    if tools:
        body["tools"] = tools
        body["tool_choice"] = "auto"
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    })
    t0 = time.time()
    try:
        r = urllib.request.urlopen(req, timeout=TIMEOUT)
        d = json.loads(r.read())
        msg = d["choices"][0]["message"]
        ans = msg.get("content", "").strip() or None
        tok = d.get("usage", {}).get("total_tokens", 0)
        dt = time.time() - t0
        extra = {"cloud": True, "model": model, "tok": tok, "time_s": round(dt, 1)}
        tc = msg.get("tool_calls")
        if tc:
            extra["tool_calls"] = tc
        return ans, extra
    except Exception as e:
        return None, {"cloud": True, "error": str(e)[:100]}


def chat(sys_prompt, user_prompt, max_tokens=256, tools=None):
    """优先云端, 失败返回 None (调用方退本地)。支持 tools (function calling)。"""
    cfg = _load_cfg()
    if not is_configured():
        return None, {"cloud": False, "reason": "no config"}

    # 逐个试后端 (配置可含多个)
    backends = cfg.get("backends", [])
    if not backends:
        # 兼容旧格式: 单后端直接在顶层
        backends = [{
            "name": cfg.get("name", "default"),
            "endpoint": cfg.get("endpoint", "https://api.deepseek.com"),
            "api_key": cfg.get("api_key", ""),
            "model": cfg.get("model", "deepseek-chat"),
        }]

    for be in backends:
        ans, meta = _chat_openai_compat(
            be.get("endpoint", ""),
            be.get("api_key", ""),
            be.get("model", "deepseek-chat"),
            sys_prompt, user_prompt, max_tokens,
            chat_path=be.get("chat_path", "/v1/chat/completions"),
            tools=tools,
        )
        if ans or meta.get("tool_calls"):
            # 有回答或有工具调用都算成功
            meta["backend"] = be.get("name", "?")
            return ans, meta
        # 这个后端失败, 试下一个

    # 全部失败
    return None, {"cloud": False, "reason": "all backends failed"}


# ── 便捷函数 ──

def is_configured():
    cfg = _load_cfg()
    if not cfg:
        return False
    for b in cfg.get("backends", [cfg]):
        k = b.get("api_key", "")
        if k and k not in ("YOUR_DEEPSEEK_API_KEY_HERE", "你的智谱API_KEY", "你的阿里百炼API_KEY"):
            return True
    return False


def list_backends():
    cfg = _load_cfg()
    bs = cfg.get("backends", [])
    if not bs and cfg.get("api_key"):
        return ["%s (%s)" % (cfg.get("name", "default"), cfg.get("model", "?"))]
    return ["%s (%s)" % (b.get("name", "?"), b.get("model", "?")) for b in bs]


if __name__ == "__main__":
    print("configured:", is_configured())
    if is_configured():
        print("backends:", list_backends())
        ans, meta = chat("你是助手", "说一句你好", max_tokens=64)
        print("A:", ans)
        print("M:", meta)
