"""屏幕空间特效：弹道曳光、枪口火光、碎片、飘字、命中标记。"""

from __future__ import annotations

import math
import random

import pygame

import config as C
from engine import clamp


class Effects:
    def __init__(self):
        self.tracers: list[dict] = []
        self.particles: list[dict] = []
        self.popups: list[dict] = []
        self.muzzle = 0.0
        self.hitmark = 0.0
        self.hitmark_head = False
        self.shake = 0.0

    # -- 生成 ----------------------------------------------------------

    def add_tracer(self, x0, y0, x1, y1):
        self.tracers.append({"a": (x0, y0), "b": (x1, y1), "t": 0.055, "life": 0.055})

    def add_muzzle(self):
        self.muzzle = 0.045

    def add_hitmark(self, head: bool):
        self.hitmark = 0.16
        self.hitmark_head = head

    def add_shake(self, amount: float):
        self.shake = min(14.0, self.shake + amount)

    def burst(self, x, y, n, color, speed=260.0, spread=1.0, size=4.0, gravity=620.0):
        for _ in range(n):
            ang = random.uniform(-math.pi, math.pi) if spread >= 1.0 else \
                random.uniform(-math.pi * spread, math.pi * spread)
            v = speed * random.uniform(0.35, 1.0)
            self.particles.append({
                "x": x, "y": y,
                "vx": math.cos(ang) * v,
                "vy": math.sin(ang) * v - speed * 0.25,
                "t": random.uniform(0.30, 0.62),
                "life": 0.62,
                "c": color,
                "s": size * random.uniform(0.6, 1.35),
                "g": gravity,
            })

    def popup(self, x, y, text, color, big=False):
        self.popups.append({"x": x, "y": y, "text": text, "c": color,
                            "t": 0.85, "life": 0.85, "big": big})

    # -- 更新 ----------------------------------------------------------

    def update(self, dt: float):
        for lst, key in ((self.tracers, "t"), (self.particles, "t"), (self.popups, "t")):
            for it in lst:
                it[key] -= dt
            lst[:] = [it for it in lst if it[key] > 0]

        for p in self.particles:
            p["vy"] += p["g"] * dt
            p["x"] += p["vx"] * dt
            p["y"] += p["vy"] * dt
            p["vx"] *= (1.0 - 2.2 * dt)

        for p in self.popups:
            p["y"] -= 42.0 * dt

        self.muzzle = max(0.0, self.muzzle - dt)
        self.hitmark = max(0.0, self.hitmark - dt)
        self.shake *= max(0.0, 1.0 - 11.0 * dt)

    # -- 绘制 ----------------------------------------------------------

    def draw_world_fx(self, surf: pygame.Surface):
        for tr in self.tracers:
            a = tr["t"] / tr["life"]
            col = (int(C.C_TRACER[0]), int(C.C_TRACER[1] * a), int(C.C_TRACER[2] * a * 0.5))
            pygame.draw.line(surf, col, tr["a"], tr["b"], 2)

        for p in self.particles:
            a = clamp(p["t"] / p["life"], 0.0, 1.0)
            s = max(1, int(p["s"] * (0.45 + 0.55 * a)))
            col = (int(p["c"][0] * a), int(p["c"][1] * a), int(p["c"][2] * a))
            pygame.draw.rect(surf, col, (int(p["x"]), int(p["y"]), s, s))

    def draw_hud_fx(self, surf: pygame.Surface, font, cx: float, cy: float):
        for p in self.popups:
            a = clamp(p["t"] / p["life"], 0.0, 1.0)
            col = (int(p["c"][0]), int(p["c"][1]), int(p["c"][2]))
            img = font.render(p["text"], True, col)
            img.set_alpha(int(255 * a))
            surf.blit(img, (int(p["x"] - img.get_width() * 0.5),
                            int(p["y"] - img.get_height() * 0.5)))

        if self.hitmark > 0:
            a = clamp(self.hitmark / 0.16, 0.0, 1.0)
            col = C.C_BOT_HEAD if self.hitmark_head else C.C_MARK
            col = (int(col[0] * a), int(col[1] * a), int(col[2] * a))
            r = 7.0 + (1.0 - a) * 5.0
            for sx, sy in ((1, 1), (1, -1), (-1, 1), (-1, -1)):
                pygame.draw.line(
                    surf, col,
                    (cx + sx * r, cy + sy * r),
                    (cx + sx * (r + 7), cy + sy * (r + 7)), 2)

    def shake_offset(self):
        if self.shake < 0.05:
            return 0.0, 0.0
        return (random.uniform(-self.shake, self.shake),
                random.uniform(-self.shake, self.shake))
