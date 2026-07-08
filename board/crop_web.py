import os, csv, json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = 8080
def _logdir():
    for d in ("/userdata", "/run/media/mmcblk1p1"):   # 优先 eMMC, 与 demo 一致(TF卡曾损坏)
        if os.path.isdir(d) and os.access(d, os.W_OK):
            try:
                t = os.path.join(d, ".wtest")
                open(t, "w").close(); os.remove(t)
                return d
            except OSError:
                continue
    return "."


LOGDIR = _logdir()
CSVPATH = os.path.join(LOGDIR, "crop_log.csv")
CAPDIR = os.path.join(LOGDIR, "captures")
LIVE = "/root/demo/live_out.jpg"
SENSORS = "/userdata/sensors.json"
TWIN_DIR = "/userdata/twin"
MIME = {".html": "text/html; charset=utf-8", ".js": "application/javascript",
        ".css": "text/css", ".glb": "model/gltf-binary", ".json": "application/json",
        ".png": "image/png", ".jpg": "image/jpeg", ".svg": "image/svg+xml",
        ".ico": "image/x-icon", ".woff2": "font/woff2"}

CN = {"bacterial_spot": "细菌性斑点", "early_blight": "早疫病", "late_blight": "晚疫病",
      "leaf_mold": "叶霉病", "leaf_miner": "潜叶蝇", "mosaic_virus": "花叶病毒",
      "septoria": "斑枯病", "spider_mites": "红蜘蛛", "yellow_leaf_curl_virus": "黄化曲叶病毒"}
DISEASES = list(CN.keys())


def read_csv():
    if not os.path.exists(CSVPATH):
        return []
    try:
        with open(CSVPATH, newline="") as f:
            return list(csv.DictReader(f))
    except OSError:
        return []


PAGE = """<!doctype html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>作物AI检测 · 远程监控</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,"Microsoft YaHei",sans-serif;background:#14141a;color:#e8e8ec;padding:14px}
h1{font-size:1.35rem;color:#50dcff}
.sub{color:#888;font-size:.8rem;margin:4px 0 16px}
.grid{display:grid;grid-template-columns:1fr;gap:14px;max-width:960px;margin:0 auto}
@media(min-width:720px){.grid{grid-template-columns:1.35fr 1fr}}
.card{background:#1e1e28;border-radius:12px;padding:16px;box-shadow:0 2px 10px rgba(0,0,0,.3)}
.card h2{font-size:1rem;color:#ffd728;margin-bottom:11px}
.live img{width:100%;border-radius:8px;display:block;background:#000;min-height:180px}
.stat{display:flex;justify-content:space-between;padding:8px 0;border-bottom:1px solid #2a2a36;font-size:.97rem}
.stat:last-child{border:0}
.stat .v{font-weight:700}
.green{color:#5aff64}.red{color:#ff5a5a}.cyan{color:#50dcff}.yel{color:#ffd728}
.dis{padding:7px 0;color:#ff7a7a;font-size:.97rem;border-bottom:1px solid #2a2a36}
.none{color:#5aff64;font-size:.97rem}
.gallery{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:10px;max-width:960px;margin:12px auto 0}
.gallery .card{padding:8px}
.gallery img{width:100%;border-radius:6px;cursor:pointer;background:#000}
.gallery .cap{font-size:.74rem;color:#bbb;margin-top:6px}
.ts{color:#666;font-size:.76rem;text-align:center;margin-top:14px}
.twinbtn{display:block;max-width:960px;margin:0 auto 16px;text-align:center;background:linear-gradient(135deg,#0e7a37,#3fcf6e);color:#fff;text-decoration:none;padding:11px;border-radius:10px;font-weight:700;box-shadow:0 2px 12px #0e7a3766}
.twinbtn:hover{filter:brightness(1.1)}
</style></head><body>
<h1>🍅 作物AI检测 · 远程监控</h1>
<div class="sub">实时画面 / 产量估算 / 病害预警 / 环境监测 · 网页自动刷新</div>
<a href="/twin/" class="twinbtn">🌐 进入 3D 数字孪生看板 →</a>
<div class="grid">
  <div class="card live"><h2>实时画面</h2><img id="live" src="/live.jpg" alt="live"></div>
  <div>
    <div class="card">
      <h2>环境监测</h2>
      <div class="stat"><span>🌡️ 温度</span><span class="v" id="temp">-</span></div>
      <div class="stat"><span>💧 湿度</span><span class="v cyan" id="rh">-</span></div>
      <div class="stat"><span>🫁 CO₂</span><span class="v" id="co2">-</span></div>
      <div class="stat"><span>☀️ 光照</span><span class="v yel" id="lux">-</span></div>
    </div>
    <div class="card" style="margin-top:14px">
      <h2>产量估算</h2>
      <div class="stat"><span>青果</span><span class="v cyan" id="green">-</span></div>
      <div class="stat"><span>半熟</span><span class="v yel" id="half">-</span></div>
      <div class="stat"><span>红果(可采收)</span><span class="v red" id="ripe">-</span></div>
      <div class="stat"><span>红果估重</span><span class="v red" id="ripeg">-</span></div>
      <div class="stat"><span>预计总产</span><span class="v green" id="totalg">-</span></div>
      <div class="stat"><span>未来7天可采收</span><span class="v cyan" id="f7">-</span></div>
    </div>
    <div class="card" style="margin-top:14px">
      <h2>病害预警</h2>
      <div id="disease"><span class="none">加载中…</span></div>
    </div>
  </div>
</div>
<h2 style="max-width:960px;margin:24px auto 0;color:#ffd728;font-size:1rem">病害抓拍记录</h2>
<div class="gallery" id="gallery"></div>
<div class="ts" id="ts">连接中…</div>
<script>
const $=id=>document.getElementById(id);
const CN={bacterial_spot:"细菌性斑点",early_blight:"早疫病",late_blight:"晚疫病",leaf_mold:"叶霉病",leaf_miner:"潜叶蝇",mosaic_virus:"花叶病毒",septoria:"斑枯病",spider_mites:"红蜘蛛",yellow_leaf_curl_virus:"黄化曲叶病毒"};
const DIS=Object.keys(CN);
const g=x=>{x=+x||0;return x>=1000?(x/1000).toFixed(2)+" kg":x+" g";};
async function tick(){
  $("live").src="/live.jpg?t="+Date.now();
  try{
    const s=await (await fetch("/api/sensors")).json();
    if(typeof s.temp==="number"){
      $("temp").textContent=s.temp+" °C";$("rh").textContent=s.rh+" %";
      $("co2").textContent=s.co2+" ppm";$("lux").textContent=Math.round(s.lux)+" lux";
    }
  }catch(e){}
  try{
    const d=await (await fetch("/api/latest")).json();
    if(d.green!==undefined){
      $("green").textContent=d.green;$("half").textContent=d.half_ripened;$("ripe").textContent=d.fully_ripened;
      $("ripeg").textContent=g(d.est_ripe_g);$("totalg").textContent=g(d.est_total_g);
      $("f7").textContent=(d.f7d_g!==undefined&&d.f7d_g!=="")?g(d.f7d_g):"数据积累中";
      const dis=DIS.filter(k=>+d[k]>0);
      $("disease").innerHTML=dis.length?dis.map(k=>`<div class="dis">⚠ ${CN[k]} × ${d[k]}</div>`).join(""):'<span class="none">✓ 未发现病害</span>';
      $("ts").textContent="数据时间 "+d.time;
    }else{$("ts").textContent="暂无数据(等待检测)";}
  }catch(e){$("ts").textContent="连接中断";}
}
async function gallery(){
  try{
    const fs=await (await fetch("/api/captures")).json();
    $("gallery").innerHTML=fs.length?fs.map(f=>{
      const m=f.match(/^([a-z_]+)_(\\d{8})_(\\d{6})/);
      const nm=m?(CN[m[1]]||m[1]):f;
      const t=m?`${m[2].slice(4,6)}-${m[2].slice(6,8)} ${m[3].slice(0,2)}:${m[3].slice(2,4)}`:"";
      return `<div class="card"><img src="/cap/${f}" onclick="window.open('/cap/${f}')"><div class="cap">${nm}<br>${t}</div></div>`;
    }).join(""):'<div style="color:#888">暂无抓拍记录</div>';
  }catch(e){}
}
tick();gallery();setInterval(tick,2000);setInterval(gallery,15000);
</script></body></html>"""


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, ctype, body):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _file(self, path, ctype):
        if os.path.exists(path):
            with open(path, "rb") as f:
                self._send(200, ctype, f.read())
        else:
            self._send(404, "text/plain", b"not found")

    def do_GET(self):
        p = self.path.split("?")[0]
        if p in ("/", "/index.html"):
            self._file(os.path.join(TWIN_DIR, "index.html"), "text/html; charset=utf-8")
        elif p == "/api/latest":
            rows = read_csv()
            self._send(200, "application/json; charset=utf-8",
                       json.dumps(rows[-1] if rows else {}, ensure_ascii=False).encode("utf-8"))
        elif p == "/api/history":
            self._send(200, "application/json; charset=utf-8",
                       json.dumps(read_csv()[-300:], ensure_ascii=False).encode("utf-8"))
        elif p == "/api/captures":
            fs = []
            if os.path.isdir(CAPDIR):
                fs = [f for f in os.listdir(CAPDIR) if f.endswith(".jpg")]
                fs.sort(key=lambda f: os.path.getmtime(os.path.join(CAPDIR, f)), reverse=True)
            self._send(200, "application/json; charset=utf-8",
                       json.dumps(fs[:60], ensure_ascii=False).encode("utf-8"))
        elif p == "/twin" or p == "/twin/":
            self._file(os.path.join(TWIN_DIR, "index.html"), "text/html; charset=utf-8")
        elif p.startswith("/twin/"):
            fp = os.path.normpath(os.path.join(TWIN_DIR, p[len("/twin/"):]))
            if not fp.startswith(TWIN_DIR):
                self._send(403, "text/plain", b"forbidden")
            else:
                self._file(fp, MIME.get(os.path.splitext(fp)[1], "application/octet-stream"))
        elif p == "/api/sensors":
            try:
                with open(SENSORS, "rb") as f:
                    body = f.read()
            except OSError:
                body = b"{}"
            self._send(200, "application/json; charset=utf-8", body)
        elif p == "/api/plants":
            try:
                with open(os.path.join(LOGDIR, "plants.json"), "rb") as f:
                    body = f.read()
            except OSError:
                body = json.dumps({"plants": [{"id": i, "scanned": False, "green": 0, "half": 0, "ripe": 0, "disease": None, "est": 0} for i in range(8)], "current": -1, "count": 0, "summary": {"green": 0, "half": 0, "ripe": 0, "est": 0}}, ensure_ascii=False).encode("utf-8")
            self._send(200, "application/json; charset=utf-8", body)
        elif p in ("/live.jpg", "/live_cam.jpg"):
            self._file(LIVE, "image/jpeg")
        elif p.startswith("/cap/"):
            self._file(os.path.join(CAPDIR, os.path.basename(p[5:])), "image/jpeg")
        else:
            self._send(404, "text/plain", b"not found")


if __name__ == "__main__":
    print("crop web on 0.0.0.0:%d  logdir=%s" % (PORT, LOGDIR), flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), H).serve_forever()
