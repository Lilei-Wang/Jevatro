"""Jevatro 决策日志面板（本地 Web，纯标准库）。

用法: python dashboard.py  →  http://127.0.0.1:8765
功能: 运行列表 / 逐决策时间线 / Jev 问答详情 / 自动刷新跟踪进行中的对局。
"""
from __future__ import annotations

import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

LOG_DIR = Path(__file__).parent / "logs"
PORT = 8765


def load_runs():
    runs = []
    for f in sorted(LOG_DIR.glob("run_*.jsonl"), reverse=True):
        recs = []
        for line in f.read_text(encoding="utf-8").splitlines():
            try:
                recs.append(json.loads(line))
            except json.JSONDecodeError:
                pass
        result = next((r for r in recs if r.get("kind") == "result"), {})
        jev_calls = sum(1 for r in recs if r.get("kind") == "jev")
        actions = next((r.get("actions") for r in recs if r.get("kind") == "result"), None)
        cfg = "jev" if "_jev_" in f.name else "naive"
        live = result == {}
        runs.append({
            "file": f.name, "config": cfg, "live": live,
            "records": len(recs), "jev_calls": jev_calls,
            "final": result.get("final", {}), "actions": actions,
            "duration": result.get("duration"),
        })
    return runs


def load_run(name: str):
    f = LOG_DIR / name
    if not f.exists() or ".." in name:
        return []
    recs = []
    for line in f.read_text(encoding="utf-8").splitlines():
        try:
            recs.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return recs


PAGE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>Jevatro 决策面板</title>
<style>
  :root { --navy:#16233d; --navy2:#1d2f52; --red:#d9382b; --ink:#1f2733;
          --muted:#5b6675; --line:#e3e8ef; --bg:#f6f8fb; --code:#0f172a; }
  * { box-sizing:border-box; }
  body { margin:0; font-family:"Segoe UI","Microsoft YaHei",sans-serif;
         background:var(--bg); color:var(--ink); font-size:14px; }
  .layout { display:flex; height:100vh; }
  aside { width:280px; background:linear-gradient(180deg,var(--navy),var(--navy2));
          color:#c6d2e6; padding:20px 14px; overflow-y:auto; flex-shrink:0; }
  aside h1 { color:#fff; font-size:16px; margin:4px 0 2px; }
  aside .sub { font-size:12px; color:#8fa1c2; margin-bottom:14px; }
  .run { padding:10px 12px; border-radius:8px; cursor:pointer; margin-bottom:6px;
         border:1px solid transparent; }
  .run:hover { background:rgba(255,255,255,.07); }
  .run.sel { background:rgba(217,56,43,.22); border-color:rgba(217,56,43,.5); }
  .run .cfg { font-weight:700; color:#fff; font-size:13px; }
  .run.naive .cfg { color:#7db3ff; } .run.jev .cfg { color:#ff9d94; }
  .run .meta { font-size:11.5px; color:#9fb0cd; margin-top:2px; }
  .live-dot { display:inline-block; width:8px; height:8px; border-radius:50%;
              background:#2ecc71; margin-right:5px; animation:pulse 1.2s infinite; }
  @keyframes pulse { 50% { opacity:.3; } }
  main { flex:1; overflow-y:auto; padding:24px 32px; }
  .bar { display:flex; gap:10px; align-items:center; margin-bottom:18px; flex-wrap:wrap; }
  .bar h2 { margin:0; font-size:19px; }
  .bar select, .bar button, .bar label { font-size:13px; }
  button { background:var(--red); color:#fff; border:none; border-radius:7px;
           padding:6px 14px; cursor:pointer; font-weight:600; }
  button.off { background:#94a3b8; }
  .stats { display:flex; gap:10px; flex-wrap:wrap; margin-bottom:16px; }
  .stat { background:#fff; border:1px solid var(--line); border-radius:10px;
          padding:8px 16px; text-align:center; min-width:110px; }
  .stat b { display:block; font-size:17px; color:var(--red); }
  .stat span { font-size:11.5px; color:var(--muted); }
  .ev { background:#fff; border:1px solid var(--line); border-radius:10px;
        margin-bottom:8px; padding:10px 14px; }
  .ev .head { display:flex; gap:10px; align-items:center; cursor:pointer; flex-wrap:wrap; }
  .tag { font-size:11px; font-weight:700; border-radius:5px; padding:2px 8px; }
  .tag.action { background:#e8f1fd; color:#0b5cb8; }
  .tag.jev { background:#fdeaea; color:#b52a1f; }
  .tag.jev_error { background:#3b0d0a; color:#ffb4ad; }
  .tag.result { background:#1a7f4e; color:#fff; }
  .tag.game_start { background:#4c3f8f; color:#fff; }
  .tag.boot { background:#eef1f6; color:#4a5568; }
  .t { color:var(--muted); font-size:11.5px; min-width:52px; }
  .why { color:var(--muted); font-size:12px; }
  .err { color:#c0392b; font-size:12px; }
  .detail { display:none; margin-top:10px; border-top:1px dashed var(--line); padding-top:8px; }
  .ev.open .detail { display:block; }
  pre { background:var(--code); color:#dbe4f3; border-radius:8px; padding:12px;
        font-size:12px; overflow-x:auto; line-height:1.55; white-space:pre-wrap; }
  .qa { display:flex; gap:8px; flex-wrap:wrap; }
  .q { flex:1 1 260px; border:1px solid var(--line); border-radius:8px; padding:8px 10px; }
  .q .k { font-weight:700; font-size:12px; color:#0b5cb8; word-break:break-all; }
  .q .v { font-size:12px; margin-top:3px; }
  .confbar { height:5px; background:#e6eaf1; border-radius:3px; margin-top:5px; }
  .confbar i { display:block; height:100%; border-radius:3px; background:#1a7f4e; }
  .statebox { max-height:220px; overflow-y:auto; margin-bottom:8px; }
  .empty { color:var(--muted); padding:40px; text-align:center; }
</style>
</head>
<body>
<div class="layout">
  <aside>
    <h1>🃏 Jevatro 决策面板</h1>
    <div class="sub">小丑牌 × Jev · 决策与日志</div>
    <div id="runs"></div>
  </aside>
  <main>
    <div class="bar">
      <h2 id="title">选择左侧一局</h2>
      <span style="flex:1"></span>
      <label><input type="checkbox" id="follow"> 跟随最新局</label>
      <label><input type="checkbox" id="filterJev" checked> 显示 Jev 调用</label>
      <label><input type="checkbox" id="filterAction" checked> 显示动作</label>
    </div>
    <div class="stats" id="stats"></div>
    <div id="timeline"><div class="empty">← 从左侧选择一次运行</div></div>
  </main>
</div>
<script>
let runs = [], cur = null;

async function refreshRuns() {
  const r = await (await fetch('/api/runs')).json();
  runs = r;
  const el = document.getElementById('runs');
  el.innerHTML = r.map((x, i) => `
    <div class="run ${x.config} ${cur===x.file?'sel':''}" onclick="selectRun('${x.file}')">
      <div class="cfg">${x.live?'<span class="live-dot"></span>':''}${x.config.toUpperCase()} · ${x.file.replace(/^run_.*?_\d{4}/,'')}</div>
      <div class="meta">${x.live?'进行中…':(x.final.won?'🏆 胜利':'💀 ante '+x.final.ante)}
        · ${x.records}条 · ${x.jev_calls}次Jev${x.duration?' · '+x.duration+'s':''}</div>
    </div>`).join('');
}

async function selectRun(f) {
  cur = f; document.getElementById('follow').checked = false;
  await renderRun();
}

async function renderRun() {
  if (!cur) return;
  const recs = await (await fetch('/api/run/' + cur)).json();
  const title = document.getElementById('title');
  title.textContent = cur;
  const jevN = recs.filter(r => r.kind === 'jev').length;
  const acts = recs.filter(r => r.kind === 'action');
  const bad = acts.filter(r => r.error).length;
  const result = recs.find(r => r.kind === 'result');
  document.getElementById('stats').innerHTML = `
    <div class="stat"><b>${acts.length}</b><span>动作</span></div>
    <div class="stat"><b>${bad}</b><span>非法/失败</span></div>
    <div class="stat"><b>${jevN}</b><span>Jev 调用</span></div>
    <div class="stat"><b>${result ? (result.final.won ? '胜' : '败') : '…'}</b><span>结果</span></div>
    <div class="stat"><b>${result ? result.final.ante : '…'}</b><span>到达 Ante</span></div>
    <div class="stat"><b>${result ? result.duration + 's' : '…'}</b><span>时长</span></div>`;
  const showJev = document.getElementById('filterJev').checked;
  const showAct = document.getElementById('filterAction').checked;
  const tl = document.getElementById('timeline');
  tl.innerHTML = recs.filter(r =>
    (r.kind === 'jev' && showJev) || (r.kind === 'action' && showAct) ||
    ['result','game_start','boot','jev_error'].includes(r.kind)
  ).map(evHtml).join('') || '<div class="empty">（该筛选下无记录）</div>';
  tl.querySelectorAll('.head').forEach(h =>
    h.onclick = () => h.parentElement.classList.toggle('open'));
}

function evHtml(r) {
  let body = '', head = '';
  if (r.kind === 'action') {
    head = `<span class="t">${r.t}s</span><b>${r.method}</b>
            <code>${JSON.stringify(r.params)}</code>
            <span class="why">${r.extra ? whyOf(r.extra) : ''}</span>
            ${r.error ? `<span class="err">✗ ${r.error}</span>` : ''}`;
    body = `<pre>${JSON.stringify(r, null, 1)}</pre>`;
  } else if (r.kind === 'jev') {
    head = `<span class="t">${r.t}s</span><b>Jev 批量调用</b>
            <span class="why">${Object.keys(r.questions).length} 题 · ${r.latency}s</span>`;
    const qs = Object.entries(r.answers).map(([k, a]) => `
      <div class="q"><div class="k">${k}</div>
        <div class="v">${ansOf(a)}</div>
        ${a.confidence != null ? `<div class="confbar"><i style="width:${Math.round(a.confidence*100)}%"></i></div>` : ''}
        <div class="v" style="color:#8794a7;margin-top:2px">${(r.questions[k]||'').slice(0,90)}</div>
      </div>`).join('');
    body = `<div class="statebox"><pre>${r.state}</pre></div><div class="qa">${qs}</div>`;
  } else if (r.kind === 'jev_error') {
    head = `<span class="t">${r.t}s</span><b>Jev 调用失败</b><span class="err">${r.error}</span>`;
    body = `<pre>${JSON.stringify(r, null, 1)}</pre>`;
  } else if (r.kind === 'result') {
    head = `<span class="t">${r.t}s</span><b>终局</b>
            <span class="why">${r.final.won ? '🏆 通关' : '💀 失败'} · ante ${r.final.ante}</span>`;
    body = `<pre>${JSON.stringify(r, null, 1)}</pre>`;
  } else {
    head = `<span class="t">${r.t}s</span><b>${r.kind}</b>`;
    body = `<pre>${JSON.stringify(r, null, 1)}</pre>`;
  }
  return `<div class="ev"><div class="head"><span class="tag ${r.kind}">${r.kind}</span>${head}</div>
          <div class="detail">${body}</div></div>`;
}
function ansOf(a) {
  if (a.type === 'noul') return `noul = <b>${(+a.noul).toFixed(2)}</b>`;
  if (a.type === 'choice') return `→ <b>${a.choice}</b>`;
  if (a.type === 'score') return `score = <b>${(+a.score).toFixed(2)}</b> / 4`;
  return JSON.stringify(a);
}
function whyOf(e) {
  if (e.why) return e.why;
  if (e.solver) return `${e.solver.hand}=${e.solver.total.toFixed(0)}`;
  if (e.solver_fallback) return 'solver兜底: ' + e.solver_fallback.slice(0, 40);
  return '';
}

document.getElementById('filterJev').onchange = renderRun;
document.getElementById('filterAction').onchange = renderRun;
document.getElementById('follow').onchange = async e => {
  if (e.target.checked && runs.length) { cur = runs[0].file; await renderRun(); }
};
refreshRuns();
setInterval(() => { refreshRuns(); if (cur) renderRun(); }, 3000);
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/":
            body = PAGE.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif path == "/api/runs":
            self._json(load_runs())
        elif path.startswith("/api/run/"):
            name = path[len("/api/run/"):]
            if not re.fullmatch(r"run_[\w\-\.]+\.jsonl", name):
                self._json({"error": "bad name"}, 400)
            else:
                self._json(load_run(name))
        else:
            self._json({"error": "not found"}, 404)


if __name__ == "__main__":
    LOG_DIR.mkdir(exist_ok=True)
    print(f"Jevatro 决策面板 → http://127.0.0.1:{PORT}  (Ctrl+C 退出)")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
