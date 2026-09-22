"""录制 bot 实打游戏 GIF：每 2.5 秒抓一帧，共 24 帧，合成 ~60 秒演示。"""
import base64
import time
from pathlib import Path

import requests
from PIL import Image

GAME = "http://127.0.0.1:12346"
TMP = Path(__file__).parent / "logs" / "_gif_frames"
TMP.mkdir(exist_ok=True)

frames = []
print("抓帧中（约 60 秒）…", flush=True)
for i in range(24):
    try:
        p = TMP / f"f{i:02d}.png"
        requests.post(GAME, json={"jsonrpc": "2.0", "id": 1, "method": "screenshot",
                                  "params": {"path": str(p)}}, timeout=10)
        if p.exists():
            im = Image.open(p).convert("RGB")
            im.thumbnail((640, 400))     # 缩小控制体积
            frames.append(im)
    except Exception as e:
        print("帧失败:", e)
    time.sleep(2.5)

if frames:
    out = Path("article_imgs/11_实打演示.gif")
    frames[0].save(out, save_all=True, append_images=frames[1:],
                   duration=900, loop=0, optimize=True)
    print("GIF 完成:", out, out.stat().st_size // 1024, "KB", len(frames), "帧")
else:
    print("无帧可合成")
