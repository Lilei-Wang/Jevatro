# -*- coding: utf-8 -*-
"""录制"游戏 + 观测台"同框演示视频（mss 抓屏 + ffmpeg 编码 mp4）。

用法: python record_video.py [秒数]      # 默认 55 秒
输出: ../article_imgs/13_观测台实况.mp4
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import imageio
import mss
import numpy as np
from PIL import Image

OUT = Path(__file__).parent.parent / "article_imgs" / "13_观测台实况.mp4"
REGION = {"left": 0, "top": 0, "width": 2540, "height": 1060}   # 游戏(左)+观测台(右)
OUT_SIZE = (1696, 704)      # 16 的倍数，便于 h264 编码
FPS = 12


def main(seconds: float = 55.0):
    OUT.parent.mkdir(exist_ok=True)
    writer = imageio.get_writer(OUT, fps=FPS, codec="libx264", quality=7,
                                macro_block_size=1)
    n = 0
    t_end = time.time() + seconds
    with mss.mss() as sct:
        print(f"recording {seconds:.0f}s @ {FPS}fps region={REGION} -> {OUT.name}", flush=True)
        while time.time() < t_end:
            img = Image.frombytes("RGB", (REGION["width"], REGION["height"]),
                                  sct.grab(REGION).rgb)
            if img.size != OUT_SIZE:
                img = img.resize(OUT_SIZE, Image.LANCZOS)
            writer.append_data(np.asarray(img))
            n += 1
            time.sleep(max(0.0, 1.0 / FPS - 0.02))
    writer.close()
    print(f"done: {n} frames, {n / FPS:.1f}s -> {OUT}")
    print(f"size: {OUT.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main(float(sys.argv[1]) if len(sys.argv) > 1 else 55.0)
