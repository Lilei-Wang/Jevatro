# -*- coding: utf-8 -*-
"""录制"游戏 + 观测台"同框演示 GIF（mss 抓屏 + PIL 编码）。

用法: python record_gif2.py <输出名> [秒数] [fps]
输出: ../article_imgs/<输出名>
区域: 屏幕左侧游戏窗口 + 右侧观测台窗口（与录屏布局一致）。
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import mss
from PIL import Image

OUT_DIR = Path(__file__).parent.parent / "article_imgs"
REGION = {"left": 0, "top": 0, "width": 2540, "height": 1060}
OUT_SIZE = (1270, 530)     # 缩到一半，控制 GIF 体积
FPS = 8


def main(name: str, seconds: float = 40.0, fps: int = FPS):
    OUT_DIR.mkdir(exist_ok=True)
    out = OUT_DIR / name
    frames = []
    t_end = time.time() + seconds
    with mss.mss() as sct:
        print(f"recording {seconds:.0f}s @ {fps}fps -> {name}", flush=True)
        while time.time() < t_end:
            img = Image.frombytes("RGB", (REGION["width"], REGION["height"]),
                                  sct.grab(REGION).rgb).resize(OUT_SIZE, Image.LANCZOS)
            frames.append(img.quantize(colors=256, method=Image.MEDIANCUT))
            time.sleep(max(0.0, 1.0 / fps - 0.02))
    frames[0].save(out, save_all=True, append_images=frames[1:],
                   duration=int(1000 / fps), loop=0, optimize=True)
    print(f"done: {len(frames)} frames -> {out} ({out.stat().st_size/1e6:.2f} MB)", flush=True)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "demo.gif",
         float(sys.argv[2]) if len(sys.argv) > 2 else 40.0,
         int(sys.argv[3]) if len(sys.argv) > 3 else FPS)
