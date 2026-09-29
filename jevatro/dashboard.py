"""Jevatro 决策观测台（本地 Web，纯标准库）。

用法: python dashboard.py  →  http://127.0.0.1:8765
单栏布局：
  02 决策流（全宽）  时间正序自动滚动跟随（动作/Jev/LLM 卡片，展开原文，键名中文化）
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

from card_desc import CARD_DESC
from card_zh import CARD_EN_ZH_PAYLOAD

LOG_DIR = Path(__file__).parent / "logs"
SHOT_DIR = LOG_DIR / "_shots"
PORT = 8765
GAME_API = "http://127.0.0.1:12346"

_shot_cache = {"t": 0.0, "b64": ""}

CFG_ZH = {"jev": "JEV驱动", "llm": "LLM驱动", "naive": "基线"}


def _enrich(gs: dict) -> dict:
    """给各卡区的卡补上中文释义字段 _desc（来自本地卡牌释义库）。"""
    if not isinstance(gs, dict):
        return gs
    for area in ("hand", "jokers", "consumables", "shop", "vouchers", "packs", "pack"):
        cards = (gs.get(area) or {}).get("cards")
        if isinstance(cards, list):
            for c in cards:
                if isinstance(c, dict):
                    c["_desc"] = CARD_DESC.get(c.get("key", ""), "")
    return gs


def load_runs():
    import time as _time
    files = sorted(LOG_DIR.glob("run_*.jsonl"),
                   key=lambda f: f.stat().st_mtime, reverse=True)
    now = _time.time()
    runs = []
    for f in files:
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
        # 进行中 = 无结果记录 且 最近 10 分钟内仍在写入（排除历史无 result 的测试日志）
        live = result == {} and (now - f.stat().st_mtime) < 600
        runs.append({
            "file": f.name, "config": CFG_ZH[cfg], "live": live,
            "records": len(recs),
            "jev_calls": sum(1 for r in recs if r.get("kind") == "jev"),
            "llm_calls": sum(1 for r in recs if r.get("kind") == "llm"),
            "final": result.get("final", {}), "duration": result.get("duration"),
        })
    return runs


def compute_compare() -> dict:
    """汇总全部历史日志，输出 Jev vs DeepSeek-LLM 对比数据（供 04 模块）。"""
    import time as _time
    import pricing
    agg = {"jev": {"runs": 0, "antes": [], "calls": 0, "lat": 0.0, "lat_n": 0,
                   "fails": 0, "cost": 0.0, "tin": 0, "tout": 0},
           "llm": {"runs": 0, "antes": [], "calls": 0, "lat": 0.0, "lat_n": 0,
                   "fails": 0, "cost": 0.0, "tin": 0, "tout": 0}}
    now = _time.time()
    for f in LOG_DIR.glob("run_*.jsonl"):
        if "_jev_" in f.name:
            cfg = "jev"
        elif "_llm_" in f.name:
            cfg = "llm"
        else:
            continue
        a = agg[cfg]
        recs = []
        try:
            for line in f.read_text(encoding="utf-8").splitlines():
                try:
                    recs.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        except OSError:
            continue
        result = next((r for r in recs if r.get("kind") == "result"), None)
        if result and result.get("final", {}).get("ante") is not None:
            a["runs"] += 1
            a["antes"].append(result["final"]["ante"])
        for r in recs:
            k = r.get("kind")
            if k in ("jev", "llm"):
                a["calls"] += 1
                a["lat"] += r.get("latency") or 0
                a["lat_n"] += 1
                if cfg == "jev":
                    tin, tout = r.get("in_tokens"), r.get("out_tokens")
                    if r.get("cost_usd") is not None and tin:
                        a["tin"] += tin
                        a["tout"] += tout or 0
                        a["cost"] += r.get("cost_usd", 0.0)
                    else:
                        est = pricing.est_tokens(r.get("state", "") +
                                                 json.dumps(r.get("questions", {}),
                                                            ensure_ascii=False))
                        a["tin"] += est
                        a["cost"] += pricing.jev_cost_usd(est, 0)
                else:
                    a["tin"] += r.get("in_tokens") or 0
                    a["tout"] += r.get("out_tokens") or 0
                    if r.get("cost_usd") is not None:
                        a["cost"] += r.get("cost_usd", 0.0)
                    elif "glm" not in (r.get("model") or ""):
                        a["cost"] += pricing.llm_cost_usd(
                            r.get("in_tokens") or 0, 0, r.get("out_tokens") or 0)
            elif k in ("jev_error", "llm_error"):
                a["fails"] += 1
            elif k == "action" and cfg == "llm":
                # LLM 解析失败不落 llm_error 记录，但回退购买带 naive_fallback 标记
                # （标记可能在记录顶层 extra 或 params.extra 里）
                ex = r.get("extra") or (r.get("params") or {}).get("extra") or {}
                if "naive_fallback" in str((ex or {}).get("why", "")):
                    a["fails"] += 1
    out = {}
    for cfg, a in agg.items():
        n = max(a["runs"], 1)
        out[cfg] = {
            "runs": a["runs"],
            "ante_avg": round(sum(a["antes"]) / n, 2) if a["antes"] else None,
            "ante_max": max(a["antes"]) if a["antes"] else None,
            "calls": a["calls"],
            "lat_avg": round(a["lat"] / max(a["lat_n"], 1), 2),
            "fails": a["fails"],
            "cost_usd": round(a["cost"], 4),
            "cost_per_run": round(a["cost"] / n, 5),
            "tokens": f"{a['tin']:,}/{a['tout']:,}",
        }
    return out


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
        return _enrich(r.json().get("result")), None
    except Exception as e:
        return None, str(e)[:80]


def fetch_hint():
    """实时求解器建议：出牌阶段返回最优出牌下标（用于手牌绿框）。"""
    try:
        from solver import best_play
        gs, err = fetch_gamestate()
        if err or not isinstance(gs, dict) or gs.get("state") != "SELECTING_HAND":
            return {"indices": [], "hand": None, "total": 0}
        bp = best_play(gs)
        return {"indices": bp["indices"], "hand": bp["hand"],
                "total": round(bp["total"], 1)}
    except Exception as e:
        return {"indices": [], "hand": None, "total": 0, "error": str(e)[:80]}


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
<title>Jevatro · 决策观测台</title>
<style>
  :root{
    --bg:#0c0e12; --card:#151920; --card2:#1a1f28; --line:#2a303c;
    --txt:#e8ecf3; --muted:#9aa3b5; --dim:#5f6878;
    --green:#34d399; --red:#f87171; --blue:#60a5fa; --amber:#fbbf24;
    --mono:Consolas,'Cascadia Code',monospace;
  }
  *{box-sizing:border-box;margin:0;padding:0}
  body{background:var(--bg);color:var(--txt);
       font:14px/1.65 'Segoe UI','Microsoft YaHei',sans-serif}
  header{display:flex;align-items:center;gap:14px;padding:12px 22px;
         border-bottom:1px solid var(--line);background:#10141a;
         position:sticky;top:0;z-index:9}
  .logo{display:flex;align-items:center;gap:9px;font-weight:800;font-size:16px}
  .logo .chip{width:27px;height:27px;border-radius:50%;background:#e5484d;color:#fff;
    display:flex;align-items:center;justify-content:center;font-size:13px;
    border:2px dashed rgba(255,255,255,.55)}
  .lab{color:var(--muted);font-size:10.5px;letter-spacing:4px;margin-top:3px}
  #liveBanner{background:rgba(248,113,113,.12);border-bottom:1px solid #4a2a30;
    color:#ff9ba0;text-align:center;padding:8px;font-size:13px;font-weight:600;
    animation:livepulse 1.6s infinite}
  #liveBanner:hover{background:rgba(248,113,113,.2)}
  @keyframes livepulse{0%,100%{opacity:1}50%{opacity:.55}}
  .dots{display:flex;gap:16px;margin-left:auto;font-size:12.5px;color:var(--muted);
        align-items:center}
  .dot{display:flex;align-items:center;gap:6px}
  .dot i{width:8px;height:8px;border-radius:50%;background:#4b5563;display:inline-block}
  .dot.on i{background:var(--green);box-shadow:0 0 8px rgba(52,211,153,.7)}
  .dot.off i{background:var(--red)}
  select{background:var(--card2);color:var(--txt);border:1px solid var(--line);
    border-radius:7px;padding:5px 9px;font-size:12px;max-width:280px}
  label{font-size:12px;color:var(--muted);display:flex;gap:5px;align-items:center}
  .wrap{display:grid;grid-template-columns:1fr 1fr;gap:16px;
        padding:16px 22px;max-width:1720px;margin:0 auto;align-items:start}
  .wrap>div:last-child{grid-column:1/-1}
  @media(max-width:1400px){.wrap{grid-template-columns:1fr}}
  .panel{background:var(--card);border:1px solid var(--line);border-radius:13px;
         padding:16px 18px;margin-bottom:16px}
  .ptitle{font-size:12px;color:var(--muted);margin-bottom:12px;
          display:flex;align-items:center;gap:9px}
  .ptitle b{color:var(--txt);font-size:13.5px;letter-spacing:1px}
  .ptitle .no{color:var(--dim);font-family:var(--mono);font-size:11px}
  .ptitle .live{margin-left:auto;color:var(--green);font-size:11px}
  .shot{width:100%;border-radius:9px;border:1px solid var(--line);display:block;
        background:#000;min-height:110px}
  .grid4{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-top:12px}
  .stat{background:var(--card2);border:1px solid var(--line);border-radius:9px;
        padding:9px 8px;text-align:center}
  .stat b{display:block;font-size:17px;font-family:var(--mono);color:var(--txt)}
  .stat span{font-size:11px;color:var(--muted)}
  .stat b.money{color:var(--amber)} .stat b.chips{color:var(--red)}
  .rowline{display:flex;justify-content:space-between;font-size:12.5px;
           color:var(--muted);padding:3.5px 0;border-bottom:1px dashed #232935}
  .rowline b{color:var(--txt);font-family:var(--mono);font-weight:600;text-align:right}
  .sec{margin-top:12px;font-size:11px;color:var(--dim);letter-spacing:1px}
  .hand{display:flex;gap:6px;flex-wrap:wrap;margin-top:6px}
  .pcard{min-width:44px;height:60px;border-radius:8px;background:var(--card2);
         border:1px solid var(--line);display:flex;flex-direction:column;
         align-items:center;justify-content:center;font-family:var(--mono)}
  .pcard .r{font-size:16px;font-weight:700}.pcard .s{font-size:13px}
  .R{color:#ff8a8a} .B{color:#cdd8ea}
  .pcard .m{font-size:9px;color:var(--amber);margin-top:1px;max-width:42px;
            overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  .pcard.hint{outline:2px solid var(--green);box-shadow:0 0 10px rgba(52,211,153,.35)}
  .item{display:flex;justify-content:space-between;gap:8px;background:var(--card2);
        border:1px solid var(--line);border-radius:8px;padding:6px 10px;
        margin-top:6px;font-size:12px}
  .item .k{font-family:var(--mono);color:#f0c9a0;word-break:break-all}
  .item .d{color:var(--muted);font-size:11px;flex:1;padding-left:8px}
  .item .p{color:var(--amber);font-family:var(--mono);white-space:nowrap}
  .stream{position:relative}
  .streambox{display:flex;flex-direction:column;gap:10px;max-height:74vh;
             overflow-y:auto;padding-right:6px;scroll-behavior:smooth}
  .streambox::-webkit-scrollbar{width:8px}
  .streambox::-webkit-scrollbar-thumb{background:#2a303c;border-radius:4px}
  .jevbox{max-height:74vh;overflow-y:auto}
  .jevbox::-webkit-scrollbar{width:8px}
  .jevbox::-webkit-scrollbar-thumb{background:#39414f;border-radius:4px}
  .jevt{width:100%;border-collapse:collapse;font-size:12.5px;table-layout:fixed}
  .jevt th{position:sticky;top:0;background:#161a20;color:#9aa3b5;font-weight:500;
           text-align:left;padding:7px 10px;border-bottom:1px solid var(--line);z-index:1}
  .jevt td{padding:7px 10px;border-bottom:1px solid #262d3a;vertical-align:middle;
           white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .jevt tr.newest td{background:rgba(52,211,153,.07);border-bottom:1px solid #2f9e63}
  .jevt tr.newest td:first-child{box-shadow:inset 3px 0 0 #34d399}
  .badge-new{display:inline-block;margin-left:6px;padding:1px 6px;border-radius:8px;
             background:#34d399;color:#0d0f12;font-size:10px;font-weight:700}
  .jstat{display:flex;gap:26px;align-items:center;padding:10px 14px;margin-bottom:10px;
         border:1px solid var(--line);border-radius:8px;background:#10141a}
  .jstat .kv b{display:block;font-size:22px;font-family:var(--mono);color:#e8ecf3;line-height:1.1}
  .jstat .kv span{font-size:11px;color:#9aa3b5}
  .jevt .tt{color:#5f6878;font-family:var(--mono);font-size:11.5px}
  .jevt .qk{color:#fbbf24;font-family:var(--mono);font-size:11px;display:block;
            white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .jevt .qi{color:#9aa3b5;font-size:11.5px;display:block;
            white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .jevt .dv{font-size:12.5px}
  .distwrap{margin-top:4px;display:flex;flex-direction:column;gap:2px}
  .dist{display:flex;align-items:center;gap:6px;font-size:10.5px;line-height:1.3}
  .dist span{width:104px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;
             color:#9aa3b5;font-size:10px}
  .dist.chosen span{color:#34d399}
  .dist .dbar{flex:1;height:5px;border-radius:3px;background:#232935;overflow:hidden}
  .dist .dbar i{display:block;height:100%;background:#4a5568;border-radius:3px}
  .dist b{min-width:30px;text-align:right;color:#7a8496;font-weight:400;
          font-family:var(--mono);font-size:10px}
  .dist.chosen .dbar i{background:#34d399}
  .dist.chosen span,.dist.chosen b{color:#34d399;font-weight:700}
  .jevt .cbar{display:flex;align-items:center;gap:10px}
  .jevt .cbar .bar{flex:1;height:7px;border-radius:4px;background:#232935;overflow:hidden}
  .jevt .cbar .bar i{display:block;height:100%;border-radius:4px}
  .jevt .cbar b{font-family:var(--mono);font-size:12px;min-width:40px;text-align:right}
  .jevt .jerr td{color:#f87171}
  .jempty{color:#5f6878;text-align:center;padding:18px}
  .cmp{width:100%;border-collapse:collapse;font-size:13px}
  .cmp th{background:#161a20;color:#9aa3b5;font-weight:500;text-align:left;
          padding:8px 14px;border-bottom:1px solid var(--line)}
  .cmp .thjev{color:#f87171}
  .cmp .thllm{color:#60a5fa}
  .cmp td{padding:8px 14px;border-bottom:1px solid #262d3a;color:#c6cede}
  .cmp td.win{color:#34d399;font-weight:700}
  .cmp td .sub{display:block;font-size:10.5px;color:#5f6878;font-weight:400}
  .mbadge{padding:3px 10px;border-radius:10px;font-size:12px;font-weight:700}
  .mbadge.jev{background:rgba(248,113,113,.15);color:#f87171;border:1px solid #4a2a30}
  .mbadge.llm{background:rgba(96,165,250,.15);color:#60a5fa;border:1px solid #2a3a5a}
  .mcrow{display:inline-flex;gap:4px;vertical-align:middle}
  .mc{display:inline-flex;align-items:center;justify-content:center;min-width:30px;height:24px;
      padding:0 4px;border:1px solid #2a303c;border-radius:4px;background:#10141a;
      font-family:var(--mono);font-size:12px;font-weight:600}
  .mc.R{color:#f87171;border-color:#4a2a30}
  .mc.B{color:#dbe3f0;border-color:#2a303c}
  .tobot{position:sticky;bottom:6px;align-self:flex-end;background:var(--green);
         color:#06281c;border:none;border-radius:999px;padding:6px 14px;
         font-size:12px;font-weight:700;cursor:pointer;display:none;z-index:5}
  .ev{background:var(--card2);border:1px solid var(--line);border-radius:10px;
      padding:10px 13px;transition:border-color .15s}
  .ev:hover{border-color:#3a4250}
  .ev .h{display:flex;align-items:center;gap:9px;cursor:pointer;flex-wrap:wrap}
  .tag{font-size:10px;font-weight:800;letter-spacing:1px;border-radius:5px;
       padding:2px 8px;white-space:nowrap}
  .tag.action{background:#0d2b1d;color:var(--green)}
  .tag.jev{background:#331519;color:#ff9ba0}
  .tag.llm{background:#14233d;color:#8ab6ff}
  .tag.jev_error{background:#3b0d0a;color:#ffb4ad}
  .tag.result{background:#15303b;color:#7fd6ff}
  .tag.sys{background:#22242a;color:var(--muted)}
  .t{color:var(--dim);font-size:11px;font-family:var(--mono);min-width:48px}
  .sum{font-size:12.5px;color:#ccd4e2}
  .sum b{color:var(--green)} .sum i{color:var(--amber);font-style:normal}
  .why{color:var(--dim);font-size:11.5px}
  .err{color:var(--red);font-size:11.5px}
  .d{display:none;margin-top:9px;border-top:1px dashed #2a303c;padding-top:8px}
  .ev.open .d{display:block}
  pre{background:#0a0d11;border:1px solid #222833;border-radius:8px;padding:10px;
      font-size:11.5px;line-height:1.5;color:#b7c2d4;overflow-x:auto;
      white-space:pre-wrap;word-break:break-all;font-family:var(--mono);max-height:300px}
  .lbl{font-size:10.5px;color:var(--dim);margin:6px 0 4px}
  .qa{display:flex;gap:8px;flex-wrap:wrap}
  .q{flex:1 1 240px;background:#10141a;border:1px solid #232935;border-radius:8px;
     padding:8px 10px}
  .q .k{font-size:11px;font-weight:700;color:#8ab6ff;font-family:var(--mono);
        word-break:break-all}
  .q .v{font-size:12px;margin-top:3px;font-family:var(--mono);color:var(--green)}
  .q .p{font-size:10.5px;color:var(--dim);margin-top:3px}
  .bar{height:4px;background:#1e232b;border-radius:2px;margin-top:5px}
  .bar i{display:block;height:100%;border-radius:2px;background:var(--green)}
  .copy{float:right;font-size:10.5px;color:var(--muted);cursor:pointer;
        border:1px solid var(--line);border-radius:5px;padding:1px 7px}
  .copy:hover{color:var(--txt);border-color:#3a4250}
  .empty{color:var(--muted);text-align:center;padding:36px 0;font-size:13px}
  #hHint{font-size:11px;color:var(--green);margin-left:6px;font-family:var(--mono)}
  /* —— 决策过程漏斗（录屏主视图）—— */
  .funnel{display:flex;flex-direction:column;gap:11px}
  .fcard{background:#10141a;border:1px solid #232935;border-radius:11px;padding:12px 14px}
  .fhead{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
  .ftag{font-size:10px;font-weight:800;letter-spacing:1px;border-radius:5px;padding:2px 8px}
  .ftag.shop{background:#0d2b1d;color:var(--green)}
  .ftag.blind{background:#15303b;color:#7fd6ff}
  .ftag.pack{background:#33200d;color:#fbbf24}
  .ftag.reroll{background:#2a1a33;color:#c792ea}
  .fsub{color:var(--muted);font-size:11.5px}
  .fsub b{color:var(--txt)}
  .flab{font-size:10.5px;color:var(--dim);letter-spacing:1px;margin:10px 0 5px}
  .archrow{display:flex;gap:6px;flex-wrap:wrap}
  .archopt{flex:1;min-width:118px;background:#151920;border:1px solid #2a303c;border-radius:8px;
    padding:5px 9px;font-size:11px;position:relative;overflow:hidden}
  .archopt .ab{position:absolute;left:0;top:0;bottom:0;background:rgba(96,165,250,.14);z-index:0;
    border-radius:8px}
  .archopt span{position:relative;z-index:1;color:#9aa3b5}
  .archopt b{position:relative;z-index:1;float:right;font-family:var(--mono);font-size:10.5px;color:#7a8496}
  .archopt.chosen{border-color:#34d399;box-shadow:0 0 9px rgba(52,211,153,.22)}
  .archopt.chosen span{color:#34d399;font-weight:700}
  .archopt.chosen b{color:#34d399}
  .items{display:grid;grid-template-columns:repeat(auto-fill,minmax(252px,1fr));gap:9px}
  .icard{background:#151920;border:1px solid #2a303c;border-radius:10px;padding:9px 11px}
  .icard.bought{border-color:#2f9e63;background:rgba(52,211,153,.06);
    box-shadow:0 0 9px rgba(52,211,153,.14)}
  .icard .itop{display:flex;justify-content:space-between;gap:6px;align-items:baseline}
  .icard .iname{font-size:11.5px;color:#e8ecf3;font-family:var(--mono);overflow:hidden;
    text-overflow:ellipsis;white-space:nowrap;max-width:170px}
  .icard .iprice{color:var(--amber);font-family:var(--mono);font-size:11.5px;white-space:nowrap}
  .icard .itail{font-size:9.5px;color:var(--dim);font-family:var(--mono);overflow:hidden;
    text-overflow:ellipsis;white-space:nowrap;margin-top:1px}
  .dimrow{display:flex;align-items:center;gap:7px;margin-top:5px;font-size:10.5px}
  .dimrow span{width:30px;color:#9aa3b5;flex-shrink:0}
  .dimrow .dbar2{flex:1;height:6px;background:#1e232b;border-radius:3px;overflow:hidden}
  .dimrow .dbar2 i{display:block;height:100%;background:#60a5fa;border-radius:3px}
  .dimrow em{min-width:86px;text-align:right;color:#7a8496;font-style:normal;
    font-family:var(--mono);font-size:9.5px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  .dimrow b{min-width:26px;text-align:right;color:#aeb8ca;font-family:var(--mono);
    font-size:10.5px;font-weight:600}
  .vrow{margin-top:8px;padding-top:7px;border-top:1px dashed #2a303c}
  .vbar{position:relative;height:15px;background:#1e232b;border-radius:8px;overflow:hidden}
  .vbar .fill{position:absolute;left:0;top:0;bottom:0;border-radius:8px}
  .vbar .tau{position:absolute;top:0;bottom:0;width:2px;background:#fbbf24;z-index:2;
    box-shadow:0 0 5px rgba(251,191,36,.8)}
  .vlab{display:flex;justify-content:space-between;font-size:10.5px;color:#9aa3b5;margin-top:3px}
  .vlab b{font-family:var(--mono);font-size:12px}
  .outb{display:inline-block;padding:2px 9px;border-radius:9px;font-size:10.5px;font-weight:700;
    margin-left:8px}
  .outb.buy{background:rgba(52,211,153,.16);color:#34d399}
  .outb.skip{background:rgba(148,163,184,.13);color:#9aa3b5}
  .outb.poor{background:rgba(251,191,36,.13);color:#fbbf24}
  .noulrow{display:flex;align-items:center;gap:12px;margin-top:6px}
  .noulrow .nl{font-size:11.5px;color:#9aa3b5;width:150px;flex-shrink:0}
  .noulbar{position:relative;flex:1;height:17px;background:#1e232b;border-radius:9px;overflow:hidden}
  .noulbar .fill{position:absolute;left:0;top:0;bottom:0;border-radius:9px}
  .noulbar .thr{position:absolute;top:0;bottom:0;width:2px;background:#fbbf24;z-index:2;
    box-shadow:0 0 5px rgba(251,191,36,.8)}
  .noulrow b{font-family:var(--mono);font-size:13px;min-width:44px;text-align:right}
  .noulrow .verdict{font-size:11.5px;font-weight:700}
  details.rawq{margin-top:13px}
  details.rawq summary{cursor:pointer;font-size:11.5px;color:var(--dim);
    letter-spacing:1px;padding:6px 0}
  details.rawq summary:hover{color:var(--muted)}
  /* —— 求解器出牌决策卡 —— */
  .ftag.solver{background:#1d2430;color:#9fb4d8}
  .schip{display:inline-flex;align-items:center;justify-content:center;min-width:30px;height:24px;
    padding:0 4px;border:1px solid #2a303c;border-radius:4px;background:#10141a;
    font-family:var(--mono);font-size:12px;font-weight:600;margin-right:3px}
  .schip.pick{outline:2px solid #34d399;box-shadow:0 0 8px rgba(52,211,153,.4)}
  .schip.drop{opacity:.45;text-decoration:line-through}
  .sline{margin-top:8px;font-size:12px;color:#c6cede}
  .sline b{font-family:var(--mono);color:#34d399;font-size:13px}
  .sline .fm{color:#fbbf24;font-family:var(--mono)}
  /* —— LLM 决策卡 —— */
  .fcard.llmfail{border-color:#4a2a30;background:rgba(248,113,113,.05)}
  .lreason{margin-top:8px;background:#10141a;border:1px solid #232935;border-radius:8px;
    padding:8px 11px;font-size:12px;color:#c6cede;line-height:1.6}
  .lreason.bad{color:#ffb4ad;border-color:#3b2326}
</style>
</head>
<body>
<header>
  <div class="logo"><span class="chip">🃏</span>
    <div>JEVATRO<div class="lab">决策观测台</div></div></div>
  <div class="dots">
    <span class="mbadge" id="modeBadge">Jev 大脑</span>
    <span class="dot" id="dRun"><i></i>对局</span>
    <select id="runSel" onchange="selRun(this.value)"></select>
    <label><input type="checkbox" id="follow" checked>跟随最新</label>
  </div>
</header>
<div id="liveBanner" onclick="jumpLive()" style="display:none;cursor:pointer">
  🔴 有对局正在进行 · 点击此处跟随直播（当前停留在历史局）
</div>

<div class="wrap">
  <!-- 决策流（全宽） -->
  <div>
    <div class="panel">
      <div class="ptitle"><span class="no">02</span><b>决策流</b>
        <span class="live">● 实时</span></div>
      <div class="grid4">
        <div class="stat"><b id="kActs">-</b><span>动作数</span></div>
        <div class="stat"><b id="kJev">-</b><span>模型调用</span></div>
        <div class="stat"><b id="kLat">-</b><span>平均耗时</span></div>
        <div class="stat"><b id="kTok">-</b><span>令牌(入/出)</span></div>
      </div>
      <div class="stream">
        <div class="streambox" id="stream">
          <div class="empty">读取决策记录…</div>
        </div>
      </div>
    </div>
  </div>

  <!-- 决策过程（漏斗可视化 + 逐题明细） -->
  <div>
    <div class="panel">
      <div class="ptitle"><span class="no">03</span><b id="decTitle">决策过程</b>
        <span class="live" id="jStat">打分 → 加权 → 阈值 → 动作</span></div>
      <div class="jstat" id="jStatBar"></div>
      <div class="jevbox">
        <div class="funnel" id="funnel"><div class="jempty">暂无决策</div></div>
        <details class="rawq"><summary>▸ 逐题原始明细（全部题目 · 选项概率 · 置信度）</summary>
        <table class="jevt" id="jevTable">
          <thead><tr id="decCols"><th style="width:64px">时间</th><th>题目</th>
            <th style="width:250px">决策（含全选项分布）</th><th style="width:150px">置信度</th></tr></thead>
          <tbody id="jevRows"><tr><td colspan="4" class="jempty">暂无 Jev 决策</td></tr></tbody>
        </table>
        </details>
      </div>
    </div>
  </div>

  <!-- 模型对比 -->
  <div>
    <div class="panel">
      <div class="ptitle"><span class="no">04</span><b>模型对比</b>
        <span class="live">Jev vs DeepSeek-LLM · 全部历史局</span></div>
      <table class="cmp" id="cmpTable">
        <thead><tr><th style="width:180px">指标</th>
          <th><span class="thjev">🃏 Jev（判断模型）</span></th>
          <th><span class="thllm">🤖 DeepSeek-flash（LLM）</span></th></tr></thead>
        <tbody id="cmpRows"><tr><td colspan="3" class="jempty">统计中…</td></tr></tbody>
      </table>
    </div>
  </div>
</div>

<script>
/*__ZH_MAPS__*/
let cur=null, runs=[], hint={indices:[]}, lastCount=-1;

const ZH_STATE={MENU:'主菜单',BLIND_SELECT:'选择盲注',SELECTING_HAND:'出牌阶段',
  ROUND_EVAL:'回合结算',SHOP:'商店',SMODS_BOOSTER_OPENED:'开包选择',GAME_OVER:'游戏结束'};
const ZH_MOD={FOIL:'闪箔',HOLO:'镭射',POLYCHROME:'多彩',NEGATIVE:'负片',BONUS:'奖励牌',
  MULT:'倍率牌',WILD:'百搭',GLASS:'玻璃',STEEL:'钢铁',STONE:'石头',GOLD:'黄金',
  LUCKY:'幸运',RED:'红印',BLUE:'蓝印',PURPLE:'紫印',eternal:'永恒',rental:'租金',
  perishable:'易逝'};
const ZH_SET={JOKER:'小丑',PLANET:'星球',TAROT:'塔罗',SPECTRAL:'幻灵',
  VOUCHER:'兑换券',BOOSTER:'卡包',DEFAULT:'牌',ENHANCED:'强化牌'};
const SUIT={S:'♠',H:'♥',D:'♦',C:'♣'};

function esc(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/"/g,'&quot;')}
// —— 全中文化工具：卡名/牌型/理由/状态文本 ——
function zhCard(k){return CARD_ZH[k]||k}
function zhHand(n){return HAND_ZH[n]||n}
const _KEY_RE=/\b(?:j|c|v|p)_[a-z0-9_]+\b/g;
function zhWhy(s){
  let t=String(s||'');
  t=t.replace(/value=/g,'价值=').replace(/conf=/g,'置信=').replace(/arch=/g,'方向=')
     .replace(/noul=/g,'概率=').replace(/solver_can_clear/g,'求解器可过')
     .replace(/naive_fallback/g,'朴素回退').replace(/dig:/g,'挖牌:')
     .replace(/best=/g,'最优=').replace(/need=/g,'需求=')
     .replace(/jev skip/g,'Jev跳盲').replace(/jev reroll/g,'Jev重掷')
     .replace(/solver_fallback/g,'求解器兜底');
  t=t.replace(_KEY_RE,m=>zhCard(m));
  for(const [en,zh] of Object.entries(HAND_ZH)) t=t.replaceAll(en,zh);
  return t;
}
function zhStateText(t){
  let s=String(t||'');
  for(const [k,en] of Object.entries(CARD_EN)){       // 英文效果描述 → 中文（先于 key 替换）
    if(s.includes(en)) s=s.replaceAll(en,DESC_ZH[k]||en);
  }
  s=s.replace(_KEY_RE,m=>zhCard(m));
  s=s.replace(/\([A-Za-z][A-Za-z0-9' ]*\)/g,'');       // 残留英文 Label
  for(const [en,zh] of Object.entries(HAND_ZH)) s=s.replaceAll(en,zh);
  for(const k in ZH_MOD) s=s.replaceAll('['+k+']','['+ZH_MOD[k]+']');
  s=s.replace(/\bDouble Tag\b/g,'双倍标签').replace(/\bUncommon Tag\b/g,'罕见标签')
     .replace(/\bRare Tag\b/g,'稀有标签').replace(/\bTag\b/g,'标签');
  return s;
}
function modZh(m){return (m||[]).filter(x=>x&&x!=='None').map(x=>ZH_MOD[x]||x).join('/')}

async function refreshRuns(){
  runs=await (await fetch('/api/runs')).json();
  const sel=document.getElementById('runSel');
  if(document.getElementById('follow').checked && runs.length) cur=runs[0].file;
  // 直播横幅：未跟随但有进行中的局时提示一键切回（修"手动选局后钉死"的坑）
  const lb=document.getElementById('liveBanner');
  const liveRun=runs.find(r=>r.live);
  lb.style.display=(liveRun && cur!==liveRun.file)?'block':'none';
  sel.innerHTML=runs.map(r=>{
    const label=`${r.config} · ${r.file.replace(/^run_.*?_\d{4}/,'')}` +
      (r.live?' ·进行中':(r.final&&r.final.won?' ·🏆通关':' ·至底注轮'+(r.final?r.final.ante:'?')));
    return `<option value="${r.file}" ${cur===r.file?'selected':''}>${label}</option>`;
  }).join('');
  document.getElementById('dRun').className='dot '+(cur?'on':'off');
}
function selRun(f){cur=f;document.getElementById('follow').checked=false;
  lastCount=-1;renderRun();}
function jumpLive(){
  const liveRun=runs.find(r=>r.live);
  if(!liveRun)return;
  document.getElementById('follow').checked=true;
  cur=liveRun.file;lastCount=-1;renderRun();
  document.getElementById('liveBanner').style.display='none';
}

// —— 中文键名渲染：把日志记录渲染成中文可读文本（替代原始 JSON）——
const ZH_KEY={t:'时间',kind:'类型',method:'动作',params:'参数',before:'动作前',after:'动作后',
  error:'错误',extra:'备注',state:'局面',questions:'题目',answers:'回答',latency:'耗时',
  model:'模型',prompt:'请求原文',reply:'模型回复',in_tokens:'输入令牌',out_tokens:'输出令牌',
  in_hit_tokens:'缓存命中',in_miss_tokens:'缓存未命中',cost_usd:'成本(美元)',
  final:'终局',actions:'动作数',illegal:'非法动作',duration:'总耗时',
  seed:'种子',ante:'底注轮',round:'轮次',money:'金币',chips:'筹码',hands_left:'剩余手数',
  n_jokers:'小丑数',won:'是否通关',why:'理由',cards:'卡牌',confidence:'置信度',
  choice:'选择',score:'打分',noul:'概率',instructions:'题目说明',criteria:'选项',
  fallback:'回退策略',file:'文件',archetype:'方向',deck:'牌组',stake:'注级'};
const ZH_VAL={play:'出牌',discard:'弃牌',buy:'购买',sell:'卖出',skip:'跳过',select:'选盲',
  use:'使用',reroll:'重掷',pack:'开包',cash_out:'结算',next_round:'进入下轮',start:'开局',
  menu:'回主菜单',action:'动作',jev:'Jev判断',llm:'LLM判断',result:'终局',
  game_start:'开局',frozen:'冻结',jev_error:'Jev失败',llm_error:'LLM失败',boot:'启动',
  true:'是',false:'否'};
// 决策明细中文化：题目键名 + 选项标签
const ZH_OPT={pair:'对子',flush:'同花',straight:'顺子',highcard:'高牌',balanced:'均衡',
  synergy:'协同',scaling:'成长',economy:'经济',immediate:'战力'};
const ZH_QNAME={archetype:'构筑方向',skip:'跳盲判断',skip_better:'跳盲判断',
  sell_which:'卖牌选择',pick:'开包选择',reroll_worth:'重掷判断',buy:'购买判断',
  can_pass:'过关判断',shelf_has_goods:'货架存在性'};
function zhQuestion(k){
  if(ZH_QNAME[k])return ZH_QNAME[k];
  const m=String(k).match(/^(item|voucher|j|p)(\d+)(?:__(\w+))?$/);
  if(m){
    const base={item:'商品',voucher:'兑换券',j:'小丑',p:'卡'}[m[1]];
    const dim=m[3]?`·${ZH_OPT[m[3]]||m[3]}`:'';
    return `${base}${+m[2]+1}${dim}`;
  }
  return k;
}
function zhOption(k){
  if(ZH_OPT[k])return ZH_OPT[k];
  const m=String(k).match(/^(item|voucher|j|p)(\d+)$/);
  if(m){const base={item:'商品',voucher:'兑换券',j:'小丑',p:'卡'}[m[1]];return `${base}${+m[2]+1}`;}
  return k;
}
function zhJson(v,ind){
  const pad='  '.repeat(ind);
  if(v===null||v===undefined)return '无';
  if(typeof v!=='object')return ZH_VAL[String(v)]??HAND_ZH[String(v)]??zhCard(String(v));
  if(Array.isArray(v))return '['+v.map(x=>zhJson(x,ind+1)).join(', ')+']';
  return '\n'+Object.entries(v).map(([k,val])=>
    `${pad}  ${ZH_KEY[k]||k}: ${zhJson(val,ind+1)}`).join('\n');
}

function nearBottom(el){return el.scrollHeight-el.scrollTop-el.clientHeight<48}
function jumpBottom(){const el=document.getElementById('stream');
  el.scrollTop=0;}
async function renderRun(){
  if(!cur)return;
  const recs=await (await fetch('/api/run/'+cur)).json();
  const isLLM=/_llm_/.test(cur);
  const mb=document.getElementById('modeBadge');
  mb.textContent=isLLM?'DeepSeek-LLM 大脑':'Jev 大脑';
  mb.className='mbadge '+(isLLM?'llm':'jev');
  document.getElementById('decTitle').textContent=
    isLLM?'LLM 决策过程':(/_naive_/.test(cur||'')?'基线局（无模型决策）':'Jev 决策过程');
  document.getElementById('decCols').innerHTML=isLLM?
    '<th style="width:64px">时间</th><th>决策</th><th>理由</th><th style="width:150px">延迟/令牌</th>':
    '<th style="width:64px">时间</th><th>题目</th><th style="width:250px">决策（含全选项分布）</th><th style="width:150px">置信度</th>';
  const acts=recs.filter(r=>r.kind==='action');
  const jevs=recs.filter(r=>r.kind==='jev');
  const llms=recs.filter(r=>r.kind==='llm');
  const lat=[...jevs,...llms];
  const tin=llms.reduce((a,r)=>a+(r.in_tokens||0),0);
  const tout=llms.reduce((a,r)=>a+(r.out_tokens||0),0);
  document.getElementById('kActs').textContent=acts.length;
  document.getElementById('kJev').textContent=jevs.length+llms.length;
  document.getElementById('kLat').textContent=lat.length?
    (lat.reduce((a,r)=>a+(r.latency||0),0)/lat.length).toFixed(2)+'秒':'-';
  document.getElementById('kTok').textContent=llms.length?
    `${(tin/1000).toFixed(1)}K/${(tout/1000).toFixed(1)}K`:'≈'+(jevs.length*2)+'K/0';

  const box=document.getElementById('stream');
  const openIdx=[...box.querySelectorAll('.ev.open')].map(e=>e.dataset.i);
  // 最新置顶（与右侧决策过程一致）：倒序渲染，无需跟随滚动
  box.innerHTML=recs.filter(r=>r.kind!=='boot').slice().reverse()
    .map((r,i)=>evHtml(r,i)).join('')
    ||'<div class="empty">（该局无记录）</div>';
  box.querySelectorAll('.ev').forEach(el=>{
    if(openIdx.includes(el.dataset.i))el.classList.add('open');
    el.querySelector('.h').onclick=()=>el.classList.toggle('open');
    const c=el.querySelector('.copy');
    if(c)c.onclick=e=>{e.stopPropagation();navigator.clipboard.writeText(c.dataset.txt||'');
      c.textContent='已复制';setTimeout(()=>c.textContent='复制',1200);};
  });
  lastCount=recs.length;
  renderJevDecisions(recs, isLLM);
}

// —— 决策明细：Jev 局逐题+置信度 / LLM 局逐次决策+理由，最新在最上 ——
function renderJevDecisions(recs, isLLM){
  if(isLLM){renderLLMDecisions(recs);return;}
  if(/_naive_/.test(cur||'')){
    document.getElementById('funnel').innerHTML=
      '<div class="jempty" style="padding:8px">基线局：无模型决策，以下为求解器（Tier 0）出牌过程</div>'
      +mergeCards([],solverCards(recs));
    document.getElementById('jStat').textContent='基线局';
    document.getElementById('jStatBar').innerHTML='';
    document.getElementById('jevRows').innerHTML=
      '<tr><td colspan="4" class="jempty">基线局没有模型调用</td></tr>';
    return;
  }
  document.getElementById('funnel').innerHTML=mergeCards(buildFunnel(recs),solverCards(recs));
  const rows=[];
  let confSum=0,confN=0,hiN=0;
  for(const r of recs){
    if(r.kind==='jev'){
      for(const [k,a] of Object.entries(r.answers||{})){
        const c=a&&a.confidence;
        if(c!=null){confSum+=c;confN++;if(c>=0.6)hiN++;}
        rows.push({t:r.t,k,q:(r.questions||{})[k]||'',a,c,lat:r.latency});
      }
    }else if(r.kind==='jev_error'){
      rows.push({t:r.t,err:r.error||'调用失败',fb:r.fallback||''});
    }
  }
  const tb=document.getElementById('jevRows');
  if(!rows.length){tb.innerHTML='<tr><td colspan="4" class="jempty">暂无 Jev 决策</td></tr>';}
  else{
    tb.innerHTML=rows.slice(-120).reverse().map((d,idx)=>d.err?
      `<tr class="jerr"><td class="tt">${d.t}秒</td><td colspan="2">✗ ${esc(d.err).slice(0,70)}</td>
        <td>已回退${esc(d.fb).slice(0,16)}</td></tr>`:
      `<tr class="${idx===0?'newest':''}">
        <td class="tt">${d.t}秒${idx===0?'<span class="badge-new">最新</span>':''}</td>
        <td title="${esc(zhStateText(String(d.q)))}"><span class="qk">${esc(zhQuestion(d.k))}</span><span class="qi">${esc(zhStateText(String(d.q)))}</span></td>
        <td class="dv" title="${esc(ansText(d.a))}">${ansOf(d.a,dimOf(d.k))}${distHtml(d.a,dimOf(d.k))}</td>
        <td>${d.c!=null?`<div class="cbar"><div class="bar"><i style="width:${Math.round(d.c*100)}%;
          background:${d.c>=0.6?'#34d399':d.c>=0.35?'#fbbf24':'#f87171'}"></i></div><b>${(+d.c).toFixed(2)}</b></div>`
          :'<span style="color:#5f6878">无信号</span>'}</td></tr>`).join('');
  }
  document.getElementById('jStat').textContent=confN?
    `平均置信度 ${(confSum/confN).toFixed(2)}`:'逐题置信度';
  document.getElementById('jStatBar').innerHTML=confN?
    `<div class="kv"><b>${rows.length}</b><span>决策题数</span></div>
     <div class="kv"><b style="color:${(confSum/confN)>=0.5?'#34d399':'#fbbf24'}">${(confSum/confN).toFixed(2)}</b><span>平均置信度</span></div>
     <div class="kv"><b>${Math.round(hiN*100/confN)}%</b><span>高置信占比(≥0.6)</span></div>
     <div class="kv"><b>${rows.filter(d=>d.err).length}</b><span>失败回退</span></div>`:'';
}

// —— 模型对比：Jev vs DeepSeek-LLM ——
async function renderCompare(){
  try{
    const d=await (await fetch('/api/compare')).json();
    const j=d.jev,l=d.llm;
    const rows=[
      ['对局数',j.runs,l.runs,'more'],
      ['平均到达底注轮',j.ante_avg,l.ante_avg,'more'],
      ['最深底注轮',j.ante_max,l.ante_max,'more'],
      ['单次决策延迟',j.lat_avg+'秒',l.lat_avg+'秒','less'],
      ['决策调用总数',j.calls,l.calls,''],
      ['失败/回退次数',j.fails,l.fails,'less'],
      ['单局成本','$'+j.cost_per_run.toFixed(5),'$'+l.cost_per_run.toFixed(5),'less'],
      ['tokens(入/出)',j.tokens,l.tokens,''],
    ];
    document.getElementById('cmpRows').innerHTML=rows.map(([k,jv,lv,dir])=>{
      const mark=(v,better)=>{
        if(!dir||v==null||better==null)return '';
        const win=(dir==='more'?v>better:v<better);
        return win?' win':'';
      };
      return `<tr><td>${k}</td><td class="${mark(jv,lv)}">${jv??'—'}</td>
        <td class="${mark(lv,jv)}">${lv??'—'}</td></tr>`;
    }).join('');
  }catch(e){}
}
// —— LLM 决策过程卡：每次调用一张（类型/决策/推理/开销），失败态醒目 ——
function llmCards(recs){
  const cards=[];
  for(const r of recs){
    if(r.kind==='llm'){
      let j=null,ok=true;
      try{ j=JSON.parse((r.reply||'').match(/\{.*\}/s)?.[0]||'null'); }catch(e){ok=false;}
      const empty=!(r.reply||'').trim();
      const tok=`${r.in_tokens||0}入/${r.out_tokens||0}出`;
      const cost=r.cost_usd!=null?` · $${(+r.cost_usd).toFixed(4)}`:'';
      let head='',body='';
      if(empty){                                  // 思考吃满配额输出为空 → 回退
        head=`<span class="ftag blind" style="background:#3b0d0a;color:#ffb4ad">思考超限</span>
          <span class="fsub"><i>${r.latency}秒</i> · ${tok}${cost}</span>`;
        body=`<div class="lreason bad">思考 token 耗尽输出为空（${r.out_tokens||0}/2000）→ 已回退朴素策略</div>`;
      }else if(j&&Array.isArray(j.buys)){
        const items=j.buys.map(zhOption).join(' + ')||'不买';
        head=`<span class="ftag shop">商店决策</span>
          <span class="fsub"><i>${r.latency}秒</i> · ${tok}${cost}</span>
          <span class="outb ${j.buys.length?'buy':'skip'}">${j.buys.length?'→ 购买 '+items:'→ 不买'}</span>`;
        body=`<div class="lreason">${esc(zhStateText(j.reason||''))}</div>`;
      }else if(j&&('skip' in j)){
        head=`<span class="ftag blind">盲注决策</span>
          <span class="fsub"><i>${r.latency}秒</i> · ${tok}${cost}</span>
          <span class="outb ${j.skip?'buy':'skip'}">${j.skip?'→ 跳过盲注':'→ 挑战盲注'}</span>`;
        body=`<div class="lreason">${esc(zhStateText(j.reason||''))}</div>`;
      }else if(j&&('pick' in j)){
        head=`<span class="ftag pack">开包选择</span>
          <span class="fsub"><i>${r.latency}秒</i> · ${tok}${cost}</span>
          <span class="outb buy">→ ${zhOption(j.pick)}</span>`;
        body=`<div class="lreason">${esc(zhStateText(j.reason||''))}</div>`;
      }else{
        head=`<span class="ftag blind" style="background:#3b0d0a;color:#ffb4ad">解析失败</span>
          <span class="fsub"><i>${r.latency}秒</i> · ${tok}${cost}</span>`;
        body=`<div class="lreason bad">${esc((r.reply||'').slice(0,120)||'（空回复）')}</div>`;
      }
      cards.push({t:r.t,html:`<div class="fcard ${empty?'llmfail':''}"><div class="fhead">${head}</div>${body}</div>`});
    }else if(r.kind==='action'){
      const ex=r.extra||(r.params||{}).extra||{};
      if(String((ex||{}).why||'').includes('naive_fallback')){
        cards.push({t:r.t,html:`<div class="fcard llmfail"><div class="fhead">
          <span class="ftag blind" style="background:#3b0d0a;color:#ffb4ad">回退动作</span>
          <span class="fsub">${zhAct(r.method)} ${zhParams(r)} — LLM 输出不可用，朴素策略接管</span>
          </div></div>`});
      }
    }
  }
  return cards;
}
// —— LLM 决策明细：每次调用一行（时间/决策/理由/延迟与令牌） ——
function renderLLMDecisions(recs){
  document.getElementById('funnel').innerHTML=mergeCards(llmCards(recs),solverCards(recs));
  const rows=[];
  let latSum=0,tin=0,tout=0,fails=0;
  for(const r of recs){
    if(r.kind==='llm'){
      latSum+=r.latency||0;
      tin+=r.in_tokens||0;tout+=r.out_tokens||0;
      let decision='—',reason='';
      try{
        const j=JSON.parse((r.reply||'').match(/\{.*\}/s)?.[0]||'null');
        if(j){
          if(Array.isArray(j.buys))decision=j.buys.length?'购买 '+j.buys.map(zhOption).join('+'):'不买';
          else if('skip' in j)decision=j.skip?'跳过盲注':'挑战盲注';
          reason=j.reason||'';
        }else{decision='原始输出';reason=(r.reply||'').slice(0,60);}
      }catch(e){decision='解析失败';reason=(r.reply||'').slice(0,60);}
      rows.push({t:r.t,decision,reason,lat:r.latency,tok:`${r.in_tokens||0}/${r.out_tokens||0}`});
    }else if(r.kind==='llm_error'){
      fails++;rows.push({t:r.t,err:r.error||'调用失败'});
    }
  }
  // naive_fallback 回退购买也计入失败
  for(const r of recs){
    if(r.kind==='action'){
      const ex=r.extra||(r.params||{}).extra||{};
      if(String((ex||{}).why||'').includes('naive_fallback'))fails++;
    }
  }
  const tb=document.getElementById('jevRows');
  if(!rows.length){tb.innerHTML='<tr><td colspan="4" class="jempty">暂无 LLM 决策</td></tr>';}
  else{
    tb.innerHTML=rows.slice(-120).reverse().map((d,idx)=>d.err?
      `<tr class="jerr"><td class="tt">${d.t}秒</td><td colspan="2">✗ ${esc(d.err).slice(0,70)}</td><td>已回退</td></tr>`:
      `<tr class="${idx===0?'newest':''}">
        <td class="tt">${d.t}秒${idx===0?'<span class="badge-new">最新</span>':''}</td>
        <td class="dv" style="color:#60a5fa;font-weight:600">${esc(d.decision)}</td>
        <td title="${esc(d.reason)}"><span class="qi">${esc(d.reason)}</span></td>
        <td class="tt">${(d.lat||0).toFixed(1)}秒<span class="qi">${d.tok} tok</span></td></tr>`).join('');
  }
  document.getElementById('jStat').textContent=rows.length?`平均延迟 ${(latSum/Math.max(rows.length,1)).toFixed(1)}秒`:'LLM 决策';
  document.getElementById('jStatBar').innerHTML=rows.length?
    `<div class="kv"><b>${rows.length}</b><span>LLM 调用</span></div>
     <div class="kv"><b style="color:#60a5fa">${(latSum/rows.length).toFixed(1)}秒</b><span>平均延迟</span></div>
     <div class="kv"><b>${(tin/1000).toFixed(1)}K/${(tout/1000).toFixed(1)}K</b><span>令牌(入/出)</span></div>
     <div class="kv"><b>${fails}</b><span>失败/回退</span></div>`:'';
}

function ansText(a){
  if(!a)return'';
  if(a.type==='noul')return`概率 ${(+a.noul).toFixed(2)} · 置信度 ${a.confidence!=null?(+a.confidence).toFixed(2):'无'}`;
  if(a.type==='choice')return`选择 ${zhOption(a.choice)} · 置信度 ${a.confidence!=null?(+a.confidence).toFixed(2):'无'}`;
  if(a.type==='score')return`打分 ${(+a.score).toFixed(2)}/4 · 置信度 ${a.confidence!=null?(+a.confidence).toFixed(2):'无'}`;
  return JSON.stringify(a).slice(0,60);
}
// 打分量表（与后端 RUBRIC 一致）：维度 → 各档含义
const RUBRIC_ZH={
  synergy:['与现有构筑零交互甚至冲突','略相关但方向不符','中性填充','明确加强现有方向','核心拼图,改变战力曲线'],
  scaling:['无成长','一次性收益','轻微成长','每轮稳定成长','复利式成长'],
  economy:['纯花钱无回报','略亏','回本','产出大于成本','直接利息引擎'],
  immediate:['对得分完全无助','略有帮助','有一定帮助','显著提升近期得分','立刻改变能否过关']};
// 与后端 jev_layer.WEIGHTS/BUY_VALUE_TAU 保持同步（决策漏斗前端复算用）
const WEIGHTS={default:{synergy:.40,scaling:.25,economy:.15,immediate:.20},
  flush:{synergy:.50,scaling:.25,economy:.10,immediate:.15},
  pair:{synergy:.45,scaling:.25,economy:.12,immediate:.18},
  highcard:{synergy:.50,scaling:.30,economy:.08,immediate:.12},
  straight:{synergy:.45,scaling:.25,economy:.12,immediate:.18},
  balanced:{synergy:.40,scaling:.25,economy:.15,immediate:.20}};
const BLEND=0.5, TAU=0.40, TAU_EARLY=0.32;
function dimOf(k){const m=String(k).match(/__(\w+)$/);return m?m[1]:null;}
function scoreLabel(dim,val){
  const rub=RUBRIC_ZH[dim];
  return rub?rub[Math.max(0,Math.min(4,Math.round(val)))]:null;
}
// 全选项概率分布：a.probabilities = {选项: 概率}，选中/接近打分值的绿色高亮
function distHtml(a,dim){
  const p=a&&a.probabilities;
  if(!p||typeof p!=='object')return'';
  const chosen=a.type==='choice'?a.choice:
    (a.type==='score'?''+Math.round(a.score):null);
  const rows=Object.entries(p)
    .sort((x,y)=>y[1]-x[1]).slice(0,6)
    .map(([k,v])=>{
      const lab=(a.type==='score'&&RUBRIC_ZH[dim])?` ${RUBRIC_ZH[dim][+k]||''}`:'';
      return `
      <div class="dist ${k===chosen?'chosen':''}">
        <span title="${esc(zhOption(k)+lab)}">${esc(zhOption(k)+lab)}</span>
        <div class="dbar"><i style="width:${Math.min(100,Math.round(v*100))}%"></i></div>
        <b>${Math.round(v*100)}%</b>
      </div>`;}).join('');
  return `<div class="distwrap">${rows}</div>`;
}

function evHtml(r,i){
  let head='',body='';
  if(r.kind==='action'){
    const ex=r.extra||(r.params||{}).extra||{};
    const why=Object.keys(ex).length?whyOf(ex):'';
    const cardsHtml=(r.method==='play'||r.method==='discard')&&
      Array.isArray(r.params.cards)&&Array.isArray((r.before||{}).hand);
    head=`<span class="t">${r.t}秒</span><span class="tag action">动作</span>
      <b style="font-family:var(--mono);font-size:12.5px">${zhAct(r.method)}</b>
      ${cardsHtml
        ? `<span class="mcrow">${r.params.cards.map(i=>cardChip((r.before.hand||[])[i])).join('')}</span>`
        : `<code style="color:#9aa3b5;font-size:11px">${zhParams(r)}</code>`}
      <span class="why">${why}</span>
      ${r.error?`<span class="err">✗ ${esc(r.error).slice(0,66)}</span>`:''}`;
    body=copyBtn(r)+`<pre>${esc(zhJson(r,0))}</pre>`;
  }else if(r.kind==='jev'){
    const n=Object.keys(r.questions||{}).length;
    head=`<span class="t">${r.t}秒</span><span class="tag jev">JEV 判断</span>
      <span class="sum"><b>${n}</b> 题 · <i>${r.latency}秒</i></span>
      <span class="why">${archOf(r)}</span>`;
    const qs=Object.entries(r.answers||{}).map(([k,a])=>`
      <div class="q"><div class="k">${esc(zhQuestion(k))}</div>
        <div class="v">${ansOf(a,dimOf(k))}</div>
        ${a.confidence!=null?`<div class="bar"><i style="width:${Math.round(a.confidence*100)}%"></i></div>`:''}
        <div class="p">${esc(zhStateText((r.questions||{})[k]||'').slice(0,90))}</div></div>`).join('');
    body=copyBtn(r)+`<div class="lbl">发送给 Jev 的局面原文（中文转写）</div>
      <pre>${esc(zhStateText(r.state||''))}</pre>
      <div class="lbl">各题回答（含置信度）</div><div class="qa">${qs}</div>`;
  }else if(r.kind==='llm'){
    head=`<span class="t">${r.t}秒</span><span class="tag llm">LLM 判断</span>
      <span class="sum">${r.model||''} · <i>${r.latency}秒</i> · ${r.in_tokens||0}入/${r.out_tokens||0}出</span>`;
    body=copyBtn({reply:(r.reply||'')})+`<div class="lbl">请求原文（中文转写）</div>
      <pre>${esc(zhStateText((r.prompt||'').slice(0,1200)))}</pre>
      <div class="lbl">模型回复</div><pre>${esc(zhStateText(r.reply||''))}</pre>`;
  }else if(r.kind==='jev_error'){
    head=`<span class="t">${r.t}秒</span><span class="tag jev_error">JEV 失败</span>
      <span class="err">${esc(r.error||'').slice(0,76)} → 已回退${r.fallback||''}</span>`;
    body=`<pre>${esc(zhJson(r,0))}</pre>`;
  }else if(r.kind==='result'){
    head=`<span class="t">${r.t}秒</span><span class="tag result">终局</span>
      <span class="sum">${r.final&&r.final.won?'🏆 通关':'💀 失败'} · 止步底注轮 ${r.final?r.final.ante:'?'}
       · ${r.actions}动作 · ${r.duration}秒</span>`;
    body=`<pre>${esc(zhJson(r,0))}</pre>`;
  }else{
    head=`<span class="t">${r.t}秒</span><span class="tag sys">${zhSys(r.kind)}</span>`;
    body=`<pre>${esc(zhJson(r,0))}</pre>`;
  }
  return `<div class="ev" data-i="${i}"><div class="h">${head}</div>
    <div class="d">${body}</div></div>`;
}
function zhParams(r){
  const p=r.params||{};
  if(Array.isArray(p.cards))return (r.method==='discard'?'弃第':'出第')+
    p.cards.map(i=>i+1).join('/')+'张';
  if(p.card!=null)return '商品位'+(+p.card+1);
  if(p.voucher!=null)return '兑换券'+(+p.voucher+1);
  if(p.joker!=null)return '小丑位'+(+p.joker+1);
  if(p.consumable!=null)return '消耗牌'+(+p.consumable+1);
  return Object.entries(p).map(([k,v])=>`${ZH_KEY[k]||k}=${ZH_VAL[String(v)]??v}`).join(' ');
}
// 迷你牌面：key 形如 "S_A"（花色_点数），红桃/方块为红
function cardChip(key){
  if(!key||typeof key!=='string')return '<span class="mc">?</span>';
  const [s,rank]=key.split('_');
  const red=s==='H'||s==='D';
  return `<span class="mc ${red?'R':'B'}">${SUIT[s]||''}${rank||'?'}</span>`;
}
function zhAct(m){return({play:'出牌',discard:'弃牌',buy:'购买',sell:'卖出',skip:'跳过',
  select:'选盲',use:'使用',reroll:'重掷',pack:'开包',cash_out:'结算',
  next_round:'进入下轮',start:'开局',menu:'回主菜单'})[m]||m}
function zhSys(k){return({game_start:'开局',frozen:'冻结',llm_error:'LLM失败'})[k]||k}
function ansOf(a, dim){
  if(!a)return'?';
  if(a.type==='noul')return`概率 = <b>${(+a.noul).toFixed(2)}</b>`;
  if(a.type==='choice')return`选择 → <b>${zhOption(a.choice)}</b>`;
  if(a.type==='score'){
    const lab=dim?scoreLabel(dim,a.score):null;
    return`打分 = <b>${(+a.score).toFixed(2)}</b>/4${lab?`（${lab}）`:''}`;
  }
  return esc(JSON.stringify(a)).slice(0,60);
}
// =========================================================================
// 决策过程漏斗：把每次 Jev 调用重演为 打分→加权→阈值→动作 的可视化
// =========================================================================
function itemKeyOf(qText){                     // 题面提取卡牌 key（买/没买的对照依据）
  const m=String(qText||'').match(/商品\[([a-z0-9_]+)[,（(]/);
  return m?m[1]:'';
}
function itemMeta(qText){                      // 题面提取 名称+售价
  const m=String(qText||'').match(/^商品\[(.+), \$(\d+)\]/);
  if(!m)return{name:'?',price:0,tail:''};
  const parts=m[1].split(':');
  return{name:parts[0].trim(),price:+m[2],tail:(parts[1]||'').trim()};
}
function moneyOf(r){                           // state 文本提取金币
  const m=String(r.state||'').match(/金币\$(\d+)/);
  return m?+m[1]:null;
}
function blendW(arch){                         // 方向权重与 default 各半（与后端一致）
  const wA=WEIGHTS[arch]||WEIGHTS.default, wD=WEIGHTS.default;
  return Object.fromEntries(Object.keys(wD).map(k=>[k,(1-BLEND)*wA[k]+BLEND*wD[k]]));
}
function distBars(a){                          // Choice 题的全选项概率条
  const p=a&&a.probabilities; if(!p)return'';
  const chosen=a.choice;
  return '<div class="archrow">'+Object.entries(p).sort((x,y)=>y[1]-x[1]).slice(0,8)
    .map(([k,v])=>`<div class="archopt ${k===chosen?'chosen':''}">
      <i class="ab" style="width:${Math.min(100,Math.round(v*100))}%"></i>
      <span>${esc(zhOption(k))}</span><b>${Math.round(v*100)}%</b></div>`).join('')+'</div>';
}
function noulGauge(a,thr,verdictHi,verdictLo){ // Noul 题仪表（阈值黄线+判定）
  if(!a||a.noul==null)return'';
  const n=+a.noul, hi=n>=thr;
  const col=hi?'#34d399':'#f87171';
  return `<div class="noulrow">
    <div class="noulbar"><i class="fill" style="width:${Math.round(n*100)}%;background:${col}"></i>
      <i class="thr" style="left:${Math.round(thr*100)}%"></i></div>
    <b style="color:${col}">${n.toFixed(2)}</b>
    <span class="verdict" style="color:${col}">${hi?verdictHi:verdictLo}</span></div>`;
}
function buildFunnel(recs){
  const cards=[];
  const acts=recs.filter(r=>r.kind==='action');
  for(const r of recs){
    if(r.kind!=='jev')continue;
    const qs=r.questions||{}, as=r.answers||{};
    const itemKeys=Object.keys(qs).filter(k=>/^item\d+__/.test(k));
    if(itemKeys.length){cards.push({t:r.t,html:shopCard(r,qs,as,acts,itemKeys)});continue;}
    if(as.pick){cards.push({t:r.t,html:packCard(r,qs,as,acts)});continue;}
    if(as.can_pass||as.skip_better){cards.push({t:r.t,html:blindCard(r,qs,as,acts)});continue;}
    if(as.shelf_has_goods||as.reroll_worth){cards.push({t:r.t,html:rerollCard(r,qs,as,acts)});}
  }
  return cards;
}
// —— 求解器出牌/弃牌决策卡（Tier 0 也进决策过程时间线）——
function solverCards(recs){
  const out=[];
  for(const r of recs){
    if(r.kind!=='action'||(r.method!=='play'&&r.method!=='discard'))continue;
    const b=r.before||{};
    const hand=Array.isArray(b.hand)?b.hand:[];
    const cards=(r.params||{}).cards||[];
    const ex=r.extra||(r.params||{}).extra||{};
    const sv=ex.solver||{};
    const ctx=`ante${b.ante??'?'} r${b.round??'?'}`;
    const chips=hand.map((k,i)=>cardChip(k).replace('class="mc',
      `class="schip ${(r.method==='play'&&cards.includes(i))?'pick':(r.method==='discard'&&cards.includes(i))?'drop':''}`));
    let line='';
    if(r.method==='play'&&sv.hand){
      line=`牌型 <b>${zhHand(sv.hand)}</b> = <span class="fm">${Math.round(sv.chips)}</span> ×
        <span class="fm">${Math.round(sv.mult)}</span> = <b>${Math.round(sv.total)}</b> 分 · 剩${b.hands_left??'?'}手`;
      if(ex.solver_fallback) line+=' · <span style="color:#f87171">兜底出牌</span>';
    }else if(r.method==='discard'){
      const m=String(ex.why||'').match(/best=([\d.]+)\/need=(\d+)/);
      line=m?`挖牌：当前最优 <b>${m[1]}</b> / 需求 <b>${m[2]}</b> → 弃边缘牌换机会`
            :'弃边缘牌（保最优组合方向）';
    }
    out.push({t:r.t,html:`<div class="fcard"><div class="fhead">
      <span class="ftag solver">⚙ 求解器${r.method==='play'?'出牌':'弃牌'}</span>
      <span class="fsub">${ctx}</span>
      <span class="mcrow" style="margin-left:4px">${chips.join('')}</span>
      </div>${line?`<div class="sline">${line}</div>`:''}</div>`});
  }
  return out;
}
function mergeCards(modelCards,solverCardsArr){
  return [...modelCards,...solverCardsArr].sort((a,b)=>b.t-a.t).slice(0,40)
    .map(c=>c.html).join('')||'<div class="jempty">暂无决策过程</div>';
}
function shopCard(r,qs,as,acts,itemKeys){
  const archA=as.archetype, arch=archA&&WEIGHTS[archA.choice]?archA.choice:'default';
  const w=blendW(arch);
  const money=moneyOf(r);
  // 商品分组：itemN → 四维答案
  const groups={};
  for(const k of itemKeys){
    const m=k.match(/^(item\d+)__(\w+)$/);
    if(!m)continue;
    (groups[m[1]]=groups[m[1]]||{})[m[2]]=as[k];
  }
  const itemHtml=Object.entries(groups).map(([slot,dims])=>{
    const qText=qs[slot+'__synergy']||'';
    const meta=itemMeta(qText), key=itemKeyOf(qText);
    const showName=key?zhCard(key):meta.name;          // 全中文：卡名走映射
    const showTail=key?(DESC_ZH[key]||meta.tail):meta.tail;
    let v=0;
    const dimRows=['synergy','scaling','economy','immediate'].map(dim=>{
      const a=dims[dim];
      if(!a||a.score==null)return '';
      const norm=Math.min(a.score,4)/4;
      v+=w[dim]*norm;
      const lab=scoreLabel(dim,a.score);
      return `<div class="dimrow"><span>${ZH_OPT[dim]||dim}</span>
        <div class="dbar2"><i style="width:${Math.round(norm*100)}%"></i></div>
        <em title="${esc(lab||'')}">${esc(lab||'')}</em><b>${(+a.score).toFixed(1)}</b></div>`;
    }).join('');
    const bought=acts.some(a=>a.t>=r.t&&a.method==='buy'&&
      String((a.extra||{}).why||((a.params||{}).extra||{}).why||'').startsWith(key+' '));
    const afford=(money==null||meta.price<=money);
    const pass=v>=TAU;
    const out=bought?'<span class="outb buy">✓ 已购买</span>'
      :!afford?'<span class="outb poor">钱不够</span>'
      :pass?'<span class="outb skip">过线未执行</span>'
      :'<span class="outb skip">未过线</span>';
    const vc=bought?'#34d399':pass?'#60a5fa':'#4a5568';
    return `<div class="icard ${bought?'bought':''}">
      <div class="itop"><span class="iname" title="${esc(showName)}">${esc(showName)}</span>
        <span class="iprice">$${meta.price}</span></div>
      <div class="itail" title="${esc(showTail)}">${esc(showTail)}</div>
      ${dimRows}
      <div class="vrow"><div class="vbar">
        <i class="fill" style="width:${Math.min(100,Math.round(v/0.9*100))}%;background:${vc}"></i>
        <i class="tau" style="left:${Math.round(TAU/0.9*100)}%"></i></div>
        <div class="vlab"><span>综合价值（权重混合方向=${zhOption(arch)}）${out}</span>
          <b style="color:${vc}">${v.toFixed(3)}</b></div></div></div>`;
  }).join('');
  const rr=as.shelf_has_goods||as.reroll_worth;
  const rrHtml=rr?`<div class="flab">重掷判断${as.shelf_has_goods?'（存在性反转：货架没有值得买的货 → 掷）':'（旧版价值题）'}</div>
    ${as.shelf_has_goods?noulGauge(as.shelf_has_goods,0.45,'货架有货 · 不掷','判定无货 → 重掷')
    :noulGauge(as.reroll_worth,0.5,'值得重掷','不重掷')}`:'';
  return `<div class="fcard"><div class="fhead">
    <span class="ftag shop">商店决策</span>
    <span class="fsub"><b>${Object.keys(groups).length}</b> 件商品 · <i>${r.latency}秒</i>
    ${archA?` · 方向判定 → <b>${zhOption(archA.choice||'')}</b>`:''}</span></div>
    ${archA?`<div class="flab">构筑方向（全选项概率 · 绿框为 Jev 选择）</div>${distBars(archA)}`:''}
    <div class="flab">商品四维打分 → 加权综合 → 阈值线 0.40（黄线；早局小丑 0.32）</div>
    <div class="items">${itemHtml}</div>${rrHtml}</div>`;
}
function blindCard(r,qs,as,acts){
  const a=as.can_pass||as.skip_better, isNew=!!as.can_pass;
  const act=acts.find(x=>x.t>=r.t&&(x.method==='select'||x.method==='skip'));
  const skipped=!!(act&&act.method==='skip');
  return `<div class="fcard"><div class="fhead">
    <span class="ftag blind">盲注决策</span>
    <span class="fsub">${isNew?'战力能否过关（存在性问法）':'跳过是否更优（旧版问法）'} · <i>${r.latency}秒</i>
    ${skipped?'<span class="outb buy">→ 已跳过</span>':'<span class="outb skip">→ 已挑战</span>'}</span></div>
    <div class="flab">${esc(zhStateText(String(qs[isNew?'can_pass':'skip_better']||'')).slice(0,90))}</div>
    ${isNew?noulGauge(a,0.45,'可过关 → 挑战','难过关 → 跳过')
           :noulGauge(a,0.65,'不跳 · 挑战','跳过（需>0.65，实测永不达）')}</div>`;
}
function packCard(r,qs,as,acts){
  const a=as.pick;
  return `<div class="fcard"><div class="fhead">
    <span class="ftag pack">开包选择</span>
    <span class="fsub">选择 → <b>${zhOption(a.choice)}</b> · <i>${r.latency}秒</i></span></div>
    <div class="flab">全选项概率（绿框为 Jev 选择）</div>${distBars(a)}</div>`;
}
function rerollCard(r,qs,as,acts){
  const a=as.shelf_has_goods||as.reroll_worth;
  const rolled=acts.some(x=>x.t>=r.t&&x.method==='reroll');
  return `<div class="fcard"><div class="fhead">
    <span class="ftag reroll">重掷判断</span>
    <span class="fsub">${rolled?'<span class="outb buy">→ 已重掷</span>':'<span class="outb skip">→ 未重掷</span>'}
     · <i>${r.latency}秒</i></span></div>
    ${as.shelf_has_goods?noulGauge(a,0.45,'货架有货 · 不掷','判定无货 → 重掷')
                        :noulGauge(a,0.5,'值得重掷','不重掷')}</div>`;
}
function archOf(r){const a=r.answers&&r.answers.archetype;
  return a&&a.choice?`方向判定: ${a.choice}`:''}
function whyOf(e){
  if(e.why)return esc(zhWhy(e.why)).slice(0,80);
  if(e.solver)return `${zhHand(e.solver.hand)}=${e.solver.total.toFixed(0)}分`;
  if(e.solver_fallback)return'求解器兜底';
  return'';
}
function copyBtn(o){return `<span class="copy" data-txt="${esc(JSON.stringify(o,null,1))}">复制</span>`}

refreshRuns();renderRun();renderCompare();
setInterval(()=>{refreshRuns();
  if(document.getElementById('follow').checked||!cur)renderRun();},2500);
setInterval(renderCompare,30000);
</script>
</body>
</html>
"""

# 中文映射注入：卡名/描述/牌型 → 前端常量（观测台全中文化）
PAGE = PAGE.replace("/*__ZH_MAPS__*/", CARD_EN_ZH_PAYLOAD)


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
        if path == "/api/compare":
            return self._json(compute_compare())
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
            if re.fullmatch(r"run_[\w\-\.]+\.jsonl", name):
                self._json(load_run(name))
            else:
                self._json({"error": "bad name"}, 400)
        elif path == "/api/gamestate":
            gs, err = fetch_gamestate()
            self._json({"state": gs, "error": err} if err else {"state": gs})
        elif path == "/api/hint":
            self._json(fetch_hint())
        elif path == "/api/shot":
            self._json({"b64": fetch_shot()})
        else:
            self._json({"error": "not found"}, 404)


if __name__ == "__main__":
    LOG_DIR.mkdir(exist_ok=True)
    print(f"Jevatro 决策观测台 → http://127.0.0.1:{PORT}  (Ctrl+C 退出)")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
