"""Jevatro Agent Lab —— 决策观测台（本地 Web，纯标准库）。

用法: python dashboard.py  →  http://127.0.0.1:8765
双栏布局（参考 Jev Tetris 风格）：
  左 01 PLAYGROUND      实时游戏截图 + 局面数据（盲注/金币/手牌/小丑/商店）
  右 02 DECISION STREAM  实时决策流（Jev/LLM 调用原文、动作、统计）
"""
from __future__ import annotations

import base64
import json
import re
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import requests

LOG_DIR = Path(__file__).parent / "logs"
SHOT_DIR = LOG_DIR / "_shots"
PORT = 8765
GAME_API = "http://127.0.0.1:12346"

_shot_cache = {"t": 0.0, "b64": ""}


def load_runs():
    runs = []
    for f in sorted(LOG_DIR.glob("run_*.jsonl"), reverse=True):
        recs = []
        try:
            for line in f.read_text(encoding="utf-8").splitlines():
                try:
                    recs.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        except OSError:
            continue
        result = next((r for r in recs if r.get("kind") == "result"), {})
        cfg = ("jev" if "_jev_" in f.name
               else "llm" if "_llm_" in f.name else "naive")
        runs.append({
            "file": f.name, "config": cfg, "live": result == {},
            "records": len(recs),
            "jev_calls": sum(1 for r in recs if r.get("kind") == "jev"),
            "llm_calls": sum(1 for r in recs if r.get("kind") == "llm"),
            "final": result.get("final", {}), "duration": result.get("duration"),
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


def fetch_gamestate():
    try:
        r = requests.post(GAME_API, json={"jsonrpc": "2.0", "id": 1,
                                          "method": "gamestate"}, timeout=6)
        return r.json().get("result"), None
    except Exception as e:
        return None, str(e)[:80]


def fetch_shot():
    if time.time() - _shot_cache["t"] < 3 and _shot_cache["b64"]:
        return _shot_cache["b64"]
    try:
        SHOT_DIR.mkdir(exist_ok=True)
        p = SHOT_DIR / "live.png"
        requests.post(GAME_API, json={"jsonrpc": "2.0", "id": 2,
                                      "method": "screenshot",
                                      "params": {"path": str(p)}}, timeout=10)
        b64 = base64.b64encode(p.read_bytes()).decode()
        _shot_cache.update(t=time.time(), b64=b64)
        return b64
    except Exception:
        return _shot_cache["b64"]


PAGE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>Jevatro · Agent Lab</title>
<style>
  :root{
    --bg:#0d0f12; --card:#14171c; --card2:#191d24; --line:#262b33;
    --txt:#e6e9ef; --muted:#8b93a3; --green:#22c55e; --red:#e5484d;
    --blue:#3b82f6; --amber:#f59e0b; --mono:Consolas,'Cascadia Code',monospace;
  }
  *{box-sizing:border-box;margin:0;padding:0}
  body{background:var(--bg);color:var(--txt);font:14px/1.6 'Segoe UI','Microsoft YaHei',sans-serif}
  header{display:flex;align-items:center;gap:14px;padding:12px 22px;
         border-bottom:1px solid var(--line);background:#101318;position:sticky;top:0;z-index:9}
  .logo{display:flex;align-items:center;gap:8px;font-weight:800;font-size:16px;letter-spacing:.5px}
  .logo .chip{width:26px;height:26px;border-radius:50%;background:var(--red);color:#fff;
    display:flex;align-items:center;justify-content:center;font-size:13px;
    border:2px dashed rgba(255,255,255,.5)}
  .lab{color:var(--muted);font-size:11px;letter-spacing:3px;margin-top:4px}
  .dots{display:flex;gap:14px;margin-left:auto;font-size:12px;color:var(--muted)}
  .dot{display:flex;align-items:center;gap:6px}
  .dot i{width:8px;height:8px;border-radius:50%;background:#555;display:inline-block}
  .dot.on i{background:var(--green);box-shadow:0 0 8px var(--green)}
  .dot.off i{background:var(--red)}
  select{background:var(--card2);color:var(--txt);border:1px solid var(--line);
    border-radius:6px;padding:4px 8px;font-size:12px}
  .wrap{display:grid;grid-template-columns:minmax(420px,44%) 1fr;gap:16px;padding:16px 22px;
        max-width:1560px;margin:0 auto}
  @media(max-width:980px){.wrap{grid-template-columns:1fr}}
  .panel{background:var(--card);border:1px solid var(--line);border-radius:12px;
         padding:16px 18px;margin-bottom:16px}
  .ptitle{font-size:11px;color:var(--muted);letter-spacing:2px;margin-bottom:12px;
          display:flex;align-items:center;gap:8px}
  .ptitle b{color:var(--txt);font-size:13px;letter-spacing:1px}
  .ptitle .live{margin-left:auto;color:var(--green);font-size:11px;letter-spacing:1px}
  .shot{width:100%;border-radius:8px;border:1px solid var(--line);display:block;
        background:#000;min-height:120px}
  .grid2{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-top:12px}
  .stat{background:var(--card2);border:1px solid var(--line);border-radius:8px;
        padding:8px 10px;text-align:center}
  .stat b{display:block;font-size:18px;font-family:var(--mono);color:var(--green)}
  .stat span{font-size:11px;color:var(--muted)}
  .stat b.warn{color:var(--amber)} .stat b.bad{color:var(--red)}
  .hand{display:flex;gap:6px;flex-wrap:wrap;margin-top:8px}
  .card{min-width:42px;height:58px;border-radius:7px;background:var(--card2);
        border:1px solid var(--line);display:flex;flex-direction:column;
        align-items:center;justify-content:center;font-family:var(--mono)}
  .card .r{font-size:16px;font-weight:700}.card .s{font-size:13px}
  .R{color:var(--red)} .B{color:#dbe4f3}
  .card .m{font-size:9px;color:var(--amber);margin-top:2px;max-width:40px;
           overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  .card.sel{outline:2px solid var(--green)}
  .jrow{display:flex;gap:6px;flex-wrap:wrap;margin-top:6px}
  .jok{background:var(--card2);border:1px solid #3a2f2a;border-radius:7px;padding:5px 9px;
       font-size:11.5px;font-family:var(--mono);color:#f0c9a0;max-width:100%}
  .rowline{display:flex;justify-content:space-between;font-size:12.5px;
           color:var(--muted);padding:3px 0;border-bottom:1px dashed #1e232b}
  .rowline b{color:var(--txt);font-family:var(--mono);font-weight:600}
  .stream{display:flex;flex-direction:column;gap:10px;max-height:78vh;overflow-y:auto;padding-right:4px}
  .ev{background:var(--card2);border:1px solid var(--line);border-radius:10px;padding:10px 13px}
  .ev .h{display:flex;align-items:center;gap:9px;cursor:pointer;flex-wrap:wrap}
  .tag{font-size:10px;font-weight:800;letter-spacing:1px;border-radius:5px;padding:2px 8px}
  .tag.action{background:#0e2a1a;color:var(--green)}
  .tag.jev{background:#2a1214;color:#ff8f94}
  .tag.llm{background:#12213a;color:#7fb0ff}
  .tag.jev_error{background:#3b0d0a;color:#ffb4ad}
  .tag.result{background:#1a2f3b;color:#7fd6ff}
  .tag.sys{background:#22242a;color:var(--muted)}
  .t{color:#5c6575;font-size:11px;font-family:var(--mono);min-width:48px}
  .sum{font-size:12.5px;color:#c8d0dd}
  .sum b{color:var(--green)} .sum i{color:var(--amber);font-style:normal}
  .why{color:#6b7280;font-size:11.5px}
  .err{color:var(--red);font-size:11.5px}
  .d{display:none;margin-top:9px;border-top:1px dashed #262b33;padding-top:8px}
  .ev.open .d{display:block}
  pre{background:#0b0d10;border:1px solid #1e232b;border-radius:8px;padding:10px;
      font-size:11.5px;line-height:1.5;color:#b7c2d4;overflow-x:auto;
      white-space:pre-wrap;word-break:break-all;font-family:var(--mono);max-height:300px}
  .qa{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:8px}
  .q{flex:1 1 240px;background:#10141a;border:1px solid #232833;border-radius:8px;padding:8px 10px}
  .q .k{font-size:11px;font-weight:700;color:#7fb0ff;font-family:var(--mono);
        word-break:break-all}
  .q .v{font-size:12px;margin-top:3px;font-family:var(--mono);color:var(--green)}
  .q .p{font-size:10.5px;color:#5c6575;margin-top:3px}
  .bar{height:4px;background:#1e232b;border-radius:2px;margin-top:5px}
  .bar i{display:block;height:100%;border-radius:2px;background:var(--green)}
  .copy{float:right;font-size:10.5px;color:var(--muted);cursor:pointer;
        border:1px solid var(--line);border-radius:5px;padding:1px 7px}
  .copy:hover{color:var(--txt)}
  .empty{color:var(--muted);text-align:center;padding:36px 0;font-size:13px}
  .cfgtag{font-size:10px;border-radius:4px;padding:1px 6px;font-weight:700}
  .cfgtag.jev{background:#2a1214;color:#ff8f94}
  .cfgtag.llm{background:#12213a;color:#7fb0ff}
  .cfgtag.naive{background:#22242a;color:var(--muted)}
</style>
</head>
<body>
<header>
  <div class="logo"><span class="chip">🃏</span><div>JEVATRO<div class="lab">AGENT LAB</div></div></div>
  <div class="dots">
    <span class="dot" id="dGame"><i></i>balatrobot</span>
    <span class="dot" id="dRun"><i></i>对局</span>
    <span style="min-width:200px">
      <select id="runSel" onchange="selRun(this.value)"></select>
    </span>
    <label style="font-size:12px;color:var(--muted)">
      <input type="checkbox" id="follow" checked> 跟随最新</label>
  </div>
</header>

<div class="wrap">
  <!-- 左：PLAYGROUND -->
  <div>
    <div class="panel">
      <div class="ptitle"><b>01</b> PLAYGROUND · 当前局面
        <span class="live" id="gstate">—</span></div>
      <img class="shot" id="shot" alt="游戏画面加载中…">
      <div class="grid2">
        <div class="stat"><b id="sAnte">-</b><span>Ante</span></div>
        <div class="stat"><b id="sRound">-</b><span>轮</span></div>
        <div class="stat"><b id="sMoney" class="warn">-</b><span>金币</span></div>
        <div class="stat"><b id="sChips" class="bad">-</b><span>chips/需求</span></div>
      </div>
      <div style="margin-top:12px">
        <div class="rowline"><span>状态</span><b id="gPhase">-</b></div>
        <div class="rowline"><span>手牌</span><b id="gHands">-</b></div>
        <div class="rowline"><span>盲注</span><b id="gBlind">-</b></div>
      </div>
      <div style="margin-top:10px;font-size:11px;color:var(--muted)">手牌（绿框=求解器将打出）</div>
      <div class="hand" id="handCards"></div>
      <div style="margin-top:10px;font-size:11px;color:var(--muted)">小丑</div>
      <div class="jrow" id="jokers"></div>
    </div>
  </div>

  <!-- 右：DECISION STREAM -->
  <div>
    <div class="panel">
      <div class="ptitle"><b>02</b> DECISION STREAM
        <span class="live" id="streamLive">● LIVE</span></div>
      <div class="grid2" style="grid-template-columns:repeat(4,1fr)">
        <div class="stat"><b id="kActs">-</b><span>动作</span></div>
        <div class="stat"><b id="kJev">-</b><span>Jev 调用</span></div>
        <div class="stat"><b id="kLat">-</b><span>平均耗时</span></div>
        <div class="stat"><b id="kTok">-</b><span>tokens(入/出)</span></div>
      </div>
      <div class="stream" id="stream"><div class="empty">读取决策记录…</div></div>
    </div>
  </div>
</div>

<script>
let cur = null, runs = [];

async function refreshRuns(){
  runs = await (await fetch('/api/runs')).json();
  const sel = document.getElementById('runSel');
  const follow = document.getElementById('follow').checked;
  if (follow && runs.length) cur = runs[0].file;
  sel.innerHTML = runs.map(r =>
    `<option value="${r.file}" ${cur===r.file?'selected':''}>
      ${r.config.toUpperCase()} · ${r.file.replace(/^run_.*?_\d{4}/,'')}
      ${r.live?'·进行中':(r.final&&r.final.won?'·🏆胜':'·ante'+(r.final?r.final.ante:'?'))}</option>`).join('');
  document.getElementById('dRun').className =
    'dot ' + (cur ? 'on' : 'off');
}
function selRun(f){ cur = f; document.getElementById('follow').checked = false; renderRun(); }

async function refreshGame(){
  try{
    const gs = await (await fetch('/api/gamestate')).json();
    const d = document.getElementById('dGame');
    if (gs.error){ d.className='dot off'; return; }
    d.className='dot on';
    const g = gs.state;
    document.getElementById('gPhase').textContent = g.state || '-';
    document.getElementById('sAnte').textContent = g.ante_num ?? '-';
    document.getElementById('sRound').textContent = g.round_num ?? '-';
    document.getElementById('sMoney').textContent = '$' + (g.money ?? '-');
    const r = g.round || {};
    const blind = Object.values(g.blinds||{}).find(b=>b && b.status==='CURRENT'||b && b.status==='SELECT');
    document.getElementById('sChips').textContent =
      (r.chips||0) + '/' + (blind ? blind.score : '-');
    document.getElementById('gBlind').textContent =
      blind ? `${blind.name} 需${blind.score}${blind.effect?' ('+blind.effect+')':''}` : '-';
    document.getElementById('gHands').textContent =
      `${r.hands_left??'-'}手 / ${r.discards_left??'-'}弃`;
    const hand = (g.hand||{}).cards||[];
    document.getElementById('handCards').innerHTML = hand.map(c=>{
      const v=c.value||{}, m=(c.modifier||[]).filter(x=>!['None'].includes(x));
      const red = v.suit==='H'||v.suit==='D';
      return `<div class="card"><span class="r ${red?'R':'B'}">${v.rank||'?'}</span>
        <span class="s ${red?'R':'B'}">${({S:'♠',H:'♥',D:'♦',C:'♣'})[v.suit]||''}</span>
        ${m.length?`<span class="m">${m.join('/')}</span>`:''}</div>`;}).join('')
      || '<span style="color:#5c6575;font-size:12px">（非出牌阶段）</span>';
    const jk = (g.jokers||{}).cards||[];
    document.getElementById('jokers').innerHTML = jk.map(j=>
      `<span class="jok">${j.key}</span>`).join('')
      || '<span style="color:#5c6575;font-size:12px">无</span>';
  }catch(e){}
}

async function refreshShot(){
  try{
    const d = await (await fetch('/api/shot')).json();
    if (d.b64) document.getElementById('shot').src = 'data:image/png;base64,' + d.b64;
  }catch(e){}
}

async function renderRun(){
  if (!cur) return;
  const recs = await (await fetch('/api/run/' + cur)).json();
  const acts = recs.filter(r=>r.kind==='action');
  const jevs = recs.filter(r=>r.kind==='jev');
  const llms = recs.filter(r=>r.kind==='llm');
  const lat = [...jevs,...llms];
  const tin = llms.reduce((a,r)=>a+(r.in_tokens||0),0);
  const tout = llms.reduce((a,r)=>a+(r.out_tokens||0),0);
  document.getElementById('kActs').textContent = acts.length;
  document.getElementById('kJev').textContent = jevs.length + llms.length;
  document.getElementById('kLat').textContent = lat.length ?
    (lat.reduce((a,r)=>a+(r.latency||0),0)/lat.length).toFixed(2)+'s' : '-';
  document.getElementById('kTok').textContent = llms.length ? `${(tin/1000).toFixed(1)}K/${(tout/1000).toFixed(1)}K` : '≈'+(jevs.length*2)+'K/0';

  const show = recs.slice().reverse().filter(r=>r.kind!=='boot');
  document.getElementById('stream').innerHTML = show.map(evHtml).join('')
    || '<div class="empty">（该局无记录）</div>';
  document.querySelectorAll('#stream .h').forEach(h=>
    h.onclick = () => h.parentElement.classList.toggle('open'));
  document.querySelectorAll('#stream .copy').forEach(c=>c.onclick=e=>{
    e.stopPropagation(); navigator.clipboard.writeText(c.dataset.txt||'');
    c.textContent='已复制'; setTimeout(()=>c.textContent='复制',1200);});
}

function evHtml(r){
  let head='', body='';
  if (r.kind==='action'){
    const why = r.extra ? whyOf(r.extra) : '';
    head = `<span class="t">${r.t}s</span><span class="tag action">ACTION</span>
      <b style="font-family:var(--mono);font-size:12.5px">${r.method}</b>
      <code style="color:#8b93a3;font-size:11px">${JSON.stringify(r.params).slice(0,60)}</code>
      <span class="why">${why}</span>${r.error?`<span class="err">✗ ${esc(r.error).slice(0,70)}</span>`:''}`;
    body = `<span class="copy" data-txt="${esc(JSON.stringify(r,null,1))}">复制</span><pre>${esc(JSON.stringify(r,null,1))}</pre>`;
  } else if (r.kind==='jev'){
    const n = Object.keys(r.questions||{}).length;
    head = `<span class="t">${r.t}s</span><span class="tag jev">JEV</span>
      <span class="sum"><b>${n}</b> 题 · <i>${r.latency}s</i></span>
      <span class="why">${archOf(r)}</span>`;
    const qs = Object.entries(r.answers||{}).map(([k,a])=>`
      <div class="q"><div class="k">${k}</div>
        <div class="v">${ansOf(a)}</div>
        ${a.confidence!=null?`<div class="bar"><i style="width:${Math.round(a.confidence*100)}%"></i></div>`:''}
        <div class="p">${esc((r.questions||{})[k]||'').slice(0,80)}</div></div>`).join('');
    body = `<span class="copy" data-txt="${esc(JSON.stringify(r,null,1))}">复制</span>
      <div style="font-size:10.5px;color:#5c6575;margin:4px 0">STATE 原文</div>
      <pre>${esc(r.state||'')}</pre>
      <div style="font-size:10.5px;color:#5c6575;margin:8px 0 4px">回答</div>
      <div class="qa">${qs}</div>`;
  } else if (r.kind==='llm'){
    head = `<span class="t">${r.t}s</span><span class="tag llm">LLM</span>
      <span class="sum">${r.model||''} · <i>${r.latency}s</i> · ${r.in_tokens||0}in/${r.out_tokens||0}out</span>`;
    body = `<span class="copy" data-txt="${esc((r.reply||'')+'')}">复制</span>
      <div style="font-size:10.5px;color:#5c6575;margin:4px 0">PROMPT</div>
      <pre>${esc((r.prompt||'').slice(0,1200))}</pre>
      <div style="font-size:10.5px;color:#5c6575;margin:8px 0 4px">REPLY</div>
      <pre>${esc(r.reply||'')}</pre>`;
  } else if (r.kind==='jev_error'){
    head = `<span class="t">${r.t}s</span><span class="tag jev_error">JEV失败</span>
      <span class="err">${esc(r.error||'').slice(0,80)} → ${r.fallback||''}</span>`;
    body = `<pre>${esc(JSON.stringify(r,null,1))}</pre>`;
  } else if (r.kind==='result'){
    head = `<span class="t">${r.t}s</span><span class="tag result">终局</span>
      <span class="sum">${r.final&&r.final.won?'🏆 通关':'💀 失败'} · ante ${r.final?r.final.ante:'?'}
       · ${r.actions}动作 · ${r.duration}s</span>`;
    body = `<pre>${esc(JSON.stringify(r,null,1))}</pre>`;
  } else {
    head = `<span class="t">${r.t}s</span><span class="tag sys">${r.kind}</span>`;
    body = `<pre>${esc(JSON.stringify(r,null,1))}</pre>`;
  }
  return `<div class="ev"><div class="h">${head}</div><div class="d">${body}</div></div>`;
}
function ansOf(a){
  if(!a) return '?';
  if(a.type==='noul') return `noul = <b>${(+a.noul).toFixed(2)}</b>`;
  if(a.type==='choice') return `→ <b>${a.choice}</b>`;
  if(a.type==='score') return `score = <b>${(+a.score).toFixed(2)}</b>/4`;
  return esc(JSON.stringify(a)).slice(0,60);
}
function archOf(r){
  const a = r.answers && (r.answers.archetype);
  return a && a.choice ? `方向: ${a.choice}` : '';
}
function whyOf(e){
  if(e.why) return esc(e.why).slice(0,70);
  if(e.solver) return `${e.solver.hand}=${e.solver.total.toFixed(0)}分`;
  if(e.solver_fallback) return 'solver兜底';
  return '';
}
function esc(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/"/g,'&quot;')}

refreshRuns(); renderRun();
setInterval(()=>{refreshRuns(); if(document.getElementById('follow').checked||!cur) renderRun();}, 2500);
setInterval(refreshGame, 2000);
setInterval(refreshShot, 4000);
refreshGame(); refreshShot();
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
        elif path == "/api/run/":
            self._json([])
        elif path.startswith("/api/run/"):
            name = path[len("/api/run/"):]
            if re.fullmatch(r"run_[\w\-\.]+\.jsonl", name):
                self._json(load_run(name))
            else:
                self._json({"error": "bad name"}, 400)
        elif path == "/api/gamestate":
            gs, err = fetch_gamestate()
            self._json({"state": gs, "error": err} if err else {"state": gs})
        elif path == "/api/shot":
            self._json({"b64": fetch_shot()})
        else:
            self._json({"error": "not found"}, 404)


if __name__ == "__main__":
    LOG_DIR.mkdir(exist_ok=True)
    print(f"Jevatro Agent Lab → http://127.0.0.1:{PORT}  (Ctrl+C 退出)")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
