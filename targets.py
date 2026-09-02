"""靶子与五种训练模式（照 CS2 创意工坊那套来的）。

botz     —— 靶场甩枪：一枪一个，靶子被清掉就补位，难度上来后会有横移靶
reflex   —— 闪现反应：一次只出一个，限时内打不掉就断连
tracking —— 跟枪压枪：一个高速乱跑的靶，靠持续命中攒连击
peek     —— 掩体探头：靶子从柱子/掩体后面滑出来，只露一小会儿
sniper  —— 远距狙击：右键开镜、左键单发、打完要上栓；远距小靶，不开镜几乎打不中
"""

from __future__ import annotations

import math
import random

import config as C
from engine import clamp, lerp

MODE_KEYS = ("botz", "reflex", "tracking", "peek", "sniper")

MODE_NAMES = {
    "botz": "AIM BOTZ",
    "reflex": "REFLEX",
    "tracking": "TRACKING",
    "peek": "PEEK",
    "sniper": "SNIPER",
}

MODE_HINT = {
    "botz": "甩枪点靶。站定或走位都行，打头 2.5 倍分",
    "reflex": "闪现靶。出现后只有零点几秒，纯拼反应",
    "tracking": "跟枪。黏住它别断，断 0.85 秒连击清零",
    "peek": "探头靶。从掩体后滑出来才打得着",
    "sniper": "远距狙击。右键开镜、左键单发，打完要上栓",
}


class Target:
    __slots__ = ("x", "y", "home", "kind", "hp", "h", "w", "age", "life",
                 "flash", "axis", "reach", "speed", "phase", "state", "timer",
                 "out", "sign", "waypoint", "scale")

    def __init__(self, x: float, y: float, kind: str = "static"):
        self.x = x
        self.y = y
        self.home = (x, y)
        self.kind = kind
        self.hp = C.BOT_HEALTH
        self.h = C.BOT_H
        self.w = C.BOT_W
        self.age = 0.0
        self.life = 0.0          # >0 表示限时存在
        self.flash = 0.0
        self.axis = (1.0, 0.0)
        self.reach = 1.4
        self.speed = 1.0
        self.phase = 0.0
        self.state = "rest"
        self.timer = 0.0
        self.out = 0.0
        self.sign = 1
        self.waypoint = (x, y)
        self.scale = 1.0

    @property
    def tracking(self) -> bool:
        return self.kind == "track"


class Range:
    """靶场：负责生成、移动、生命周期，不碰渲染和计分。"""

    def __init__(self, gmap, rng: random.Random | None = None):
        self.gmap = gmap
        self.rng = rng or random.Random()
        self.mode = "botz"
        self.targets: list[Target] = []
        self.pending: list[float] = []
        self.events: list[str] = []
        self.hits = 0
        self.difficulty = 0.0
        self.anchors: list[tuple] = []
        self.spawn_timer = 0.0
        self.set_mode("botz", None)

    # ------------------------------------------------------------ 模式

    def set_mode(self, mode: str, cam=None):
        self.mode = mode
        self.targets.clear()
        self.pending.clear()
        self.events.clear()
        self.hits = 0
        self.difficulty = 0.0
        self.spawn_timer = 0.0
        if cam is None:
            return
        if mode == "botz":
            self._spawn_botz(cam)
        elif mode == "reflex":
            self._spawn_reflex(cam)
        elif mode == "tracking":
            self._spawn_tracking(cam)
        elif mode == "peek":
            self.anchors = self._build_peek_anchors()
            self._spawn_peek(cam)
        elif mode == "sniper":
            self._spawn_sniper(cam)

    def update(self, dt: float, cam) -> list[str]:
        events = self.events
        events.clear()

        self.difficulty = clamp(self.hits / 200.0, 0.0, 1.0)

        for t in self.targets:
            t.age += dt
            if t.flash > 0:
                t.flash = max(0.0, t.flash - dt)

        if self.mode == "botz":
            self._update_botz(dt, cam)
        elif self.mode == "reflex":
            self._update_reflex(dt, cam)
        elif self.mode == "tracking":
            self._update_tracking(dt, cam)
        elif self.mode == "peek":
            self._update_peek(dt, cam)
        elif self.mode == "sniper":
            self._update_sniper(dt, cam)

        return events

    # ------------------------------------------------------------ 取点

    def _free_spot(self, cam, min_d=5.0, max_d=17.0, cone=None,
                   need_los=True, min_gap=6.0, tries=90, clear_r=0.55):
        for _ in range(tries):
            if cone is None:
                ang = self.rng.uniform(0.0, math.tau)
            else:
                ang = cam.yaw + self.rng.uniform(-cone, cone)
            d = self.rng.uniform(min_d, max_d)
            x = cam.x + math.cos(ang) * d
            y = cam.y + math.sin(ang) * d
            if not (1.7 <= x <= self.gmap.w - 1.7 and 1.7 <= y <= self.gmap.h - 1.7):
                continue
            if self.gmap.blocked(x, y, clear_r):
                continue
            if need_los and not self.gmap.clear_line(cam.x, cam.y, x, y):
                continue
            if any((x - t.x) ** 2 + (y - t.y) ** 2 < min_gap for t in self.targets):
                continue
            return x, y
        return None

    def _far_waypoint(self, cam, t: Target, min_d=5.0, max_d=15.0):
        for _ in range(60):
            ang = self.rng.uniform(0.0, math.tau)
            d = self.rng.uniform(min_d, max_d)
            x = cam.x + math.cos(ang) * d
            y = cam.y + math.sin(ang) * d
            if not (1.8 <= x <= self.gmap.w - 1.8 and 1.8 <= y <= self.gmap.h - 1.8):
                continue
            if self.gmap.blocked(x, y, 0.5):
                continue
            if not self.gmap.clear_line(cam.x, cam.y, x, y):
                continue
            return (x, y)
        return (t.home[0], t.home[1])

    # ------------------------------------------------------------ AIM BOTZ

    def _spawn_botz(self, cam):
        # 正在等刷新倒计时的靶子要先占住名额，否则 _update_botz 里每次都会
        # 把缺口立刻补满，RESPAWN_DELAY 等于没写。
        want = int(lerp(5, C.MAX_BOTS + 2, self.difficulty)) - len(self.pending)
        guard = 0
        while len(self.targets) < want and guard < 30:
            guard += 1
            spot = self._free_spot(cam, 5.0, 17.0, cone=math.pi)
            if spot is None:
                break
            t = Target(spot[0], spot[1])
            if self.rng.random() < 0.15 + 0.4 * self.difficulty:
                t.kind = "strafe"
                ax, ay = self.rng.uniform(-1, 1), self.rng.uniform(-1, 1)
                n = math.hypot(ax, ay) or 1.0
                t.axis = (ax / n, ay / n)
                t.reach = self.rng.uniform(0.8, 1.9)
                t.speed = self.rng.uniform(0.45, 0.85) + 0.8 * self.difficulty
                t.phase = self.rng.uniform(0.0, math.tau)
            self.targets.append(t)

    def _update_botz(self, dt, cam):
        for t in self.targets:
            if t.kind == "strafe":
                s = math.sin(t.age * t.speed * 2.0 + t.phase) * t.reach
                t.x = t.home[0] + t.axis[0] * s
                t.y = t.home[1] + t.axis[1] * s
        for i in range(len(self.pending) - 1, -1, -1):
            self.pending[i] -= dt
            if self.pending[i] <= 0:
                self.pending.pop(i)
        self._spawn_botz(cam)

    # ------------------------------------------------------------ REFLEX

    def _spawn_reflex(self, cam):
        # 刷新锥角要略大于半个 FOV（90° 的半角是 45°）：留一点转头余量，
        # 但不能太大 —— 刷在屏幕外就成了"找靶"，而不是练反应。
        spot = self._free_spot(cam, 6.0, 16.0, cone=math.radians(60), min_gap=0.0)
        if spot is None:
            spot = self._free_spot(cam, 4.0, 16.0, cone=None, min_gap=0.0, need_los=False)
        if spot is None:
            return
        t = Target(spot[0], spot[1], "reflex")
        t.life = lerp(C.REFLEX_LIFE, C.REFLEX_LIFE_MIN, self.difficulty)
        t.scale = lerp(1.0, 0.72, self.difficulty)
        t.h = C.BOT_H * t.scale
        t.w = C.BOT_W * t.scale
        t.hp = 1
        self.targets.append(t)

    def _update_reflex(self, dt, cam):
        if not self.targets:
            self.spawn_timer -= dt
            if self.spawn_timer <= 0:
                self._spawn_reflex(cam)
                self.spawn_timer = 0.45
            return
        t = self.targets[0]
        if t.life > 0 and t.age >= t.life:
            self.targets.clear()
            self.events.append("expire")
            self.spawn_timer = 0.10

    # ------------------------------------------------------------ TRACKING

    def _spawn_tracking(self, cam):
        spot = self._free_spot(cam, 7.0, 12.0, cone=math.radians(80), min_gap=0.0)
        if spot is None:
            spot = self._free_spot(cam, 5.0, 14.0, cone=None, min_gap=0.0, need_los=False)
        if spot is None:
            return
        t = Target(spot[0], spot[1], "track")
        t.hp = float("inf")
        t.h = C.BOT_H * 0.92
        t.w = C.BOT_W * 0.92
        t.speed = 3.0
        t.waypoint = self._far_waypoint(cam, t)
        self.targets.append(t)

    def _update_tracking(self, dt, cam):
        if not self.targets:
            self._spawn_tracking(cam)
            return
        t = self.targets[0]
        speed = lerp(2.6, 5.4, self.difficulty)
        wx, wy = t.waypoint
        dx, dy = wx - t.x, wy - t.y
        dist = math.hypot(dx, dy)
        if dist < 0.6:
            t.waypoint = self._far_waypoint(cam, t)
        else:
            step = speed * dt
            nx, ny = t.x + dx / dist * step, t.y + dy / dist * step
            if not self.gmap.blocked(nx, ny, 0.4):
                t.x, t.y = nx, ny
            else:
                t.waypoint = self._far_waypoint(cam, t)

    # ------------------------------------------------------------ PEEK

    def _build_peek_anchors(self):
        """空地紧邻墙体的位置，配一条沿墙面的切线作为探头方向。"""
        g = self.gmap
        out = []
        for gy in range(1, g.h - 1):
            for gx in range(1, g.w - 1):
                if g.at(gx, gy):
                    continue
                for (dx, dy) in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    if not g.at(gx + dx, gy + dy):
                        continue
                    ax, ay = -dy, dx
                    cx, cy = gx + 0.5, gy + 0.5
                    ok_a = not g.blocked(cx + ax * 2.2, cy + ay * 2.2, 0.35)
                    ok_b = not g.blocked(cx - ax * 2.2, cy - ay * 2.2, 0.35)
                    if ok_a or ok_b:
                        out.append((cx, cy, ax, ay, ok_a, ok_b))
                    break
        return out

    def _spawn_peek(self, cam):
        want = int(lerp(3, 6, self.difficulty))
        if not self.anchors:
            return
        pool = [a for a in self.anchors]
        self.rng.shuffle(pool)
        for a in pool:
            if len(self.targets) >= want:
                break
            cx, cy, ax, ay, ok_a, ok_b = a
            d = math.hypot(cx - cam.x, cy - cam.y)
            if d < 4.5 or d > 18.0:
                continue
            if any((cx - t.home[0]) ** 2 + (cy - t.home[1]) ** 2 < 16.0 for t in self.targets):
                continue
            t = Target(cx, cy, "peek")
            t.axis = (ax, ay)
            t.reach = self.rng.uniform(1.5, 2.4)
            t.state = "rest"
            t.timer = self.rng.uniform(0.0, C.PEEK_REST)
            t.sign = 1 if ok_a else -1
            self.targets.append(t)

    def _update_peek(self, dt, cam):
        # 数量随难度补齐
        want = int(lerp(3, 6, self.difficulty))
        if len(self.targets) < want:
            self._spawn_peek(cam)

        shrink = lerp(1.0, 0.62, self.difficulty)
        for t in self.targets:
            t.timer -= dt
            if t.state == "rest":
                t.out = 0.0
                if t.timer <= 0:
                    # 挑一个能真正露出来的方向
                    hx, hy = t.home
                    ax, ay = t.axis
                    plus_ok = (not self.gmap.blocked(hx + ax * t.reach, hy + ay * t.reach, 0.4)
                               and self.gmap.clear_line(cam.x, cam.y,
                                                        hx + ax * t.reach, hy + ay * t.reach))
                    minus_ok = (not self.gmap.blocked(hx - ax * t.reach, hy - ay * t.reach, 0.4)
                                and self.gmap.clear_line(cam.x, cam.y,
                                                         hx - ax * t.reach, hy - ay * t.reach))
                    if plus_ok and minus_ok:
                        t.sign = self.rng.choice((-1, 1))
                    elif plus_ok:
                        t.sign = 1
                    elif minus_ok:
                        t.sign = -1
                    t.state = "out"
            elif t.state == "out":
                t.out = min(1.0, t.out + dt / 0.22)
                if t.out >= 1.0:
                    t.state = "hold"
                    t.timer = C.PEEK_OUT * shrink
            elif t.state == "hold":
                t.out = 1.0
                if t.timer <= 0:
                    t.state = "in"
            elif t.state == "in":
                t.out = max(0.0, t.out - dt / 0.22)
                if t.out <= 0.0:
                    t.state = "rest"
                    t.timer = C.PEEK_REST * shrink

            s = t.out * t.reach * t.sign
            t.x = t.home[0] + t.axis[0] * s
            t.y = t.home[1] + t.axis[1] * s

    # ------------------------------------------------------------ SNIPER

    def _spawn_sniper(self, cam):
        # 远距小靶：必须开镜才打得中。pending 占住名额，保证上栓/刷新有延迟。
        # clear_r 取得大些（0.95），漂移幅度小（≤0.6），保证靶子永远离墙 ≥0.3，
        # 不会漂进墙里。
        want = int(lerp(4, 7, self.difficulty)) - len(self.pending)
        guard = 0
        while len(self.targets) < want and guard < 40:
            guard += 1
            spot = self._free_spot(cam, C.SNIPER_DIST_MIN, C.SNIPER_DIST_MAX,
                                   cone=math.pi, min_gap=3.0, need_los=True,
                                   clear_r=0.95, tries=200)
            if spot is None:
                spot = self._free_spot(cam, C.SNIPER_DIST_MIN, C.SNIPER_DIST_MAX,
                                       cone=None, min_gap=2.0, need_los=False,
                                       clear_r=0.95, tries=200)
            if spot is None:
                break
            t = Target(spot[0], spot[1], "sniper")
            t.hp = 1                      # 一枪毙命
            t.h = C.SNIPER_BOT_H
            t.w = C.SNIPER_BOT_W          # 比普通靶更窄
            ax, ay = self.rng.uniform(-1, 1), self.rng.uniform(-1, 1)
            n = math.hypot(ax, ay) or 1.0
            t.axis = (ax / n, ay / n)
            t.reach = self.rng.uniform(0.4, 0.6)
            t.speed = C.SNIPER_DRIFT
            t.phase = self.rng.uniform(0.0, math.tau)
            self.targets.append(t)

    def _update_sniper(self, dt, cam):
        for t in self.targets:
            # 缓慢横向漂移，制造"等到位再开枪"的节奏；漂进墙就反向，避免穿墙
            s = math.sin(t.age * t.speed * 2.0 + t.phase) * t.reach
            nx = t.home[0] + t.axis[0] * s
            ny = t.home[1] + t.axis[1] * s
            if self.gmap.blocked(nx, ny, 0.25):
                s = -s
                nx = t.home[0] + t.axis[0] * s
                ny = t.home[1] + t.axis[1] * s
            if not self.gmap.blocked(nx, ny, 0.25):
                t.x, t.y = nx, ny
        for i in range(len(self.pending) - 1, -1, -1):
            self.pending[i] -= dt
            if self.pending[i] <= 0:
                self.pending.pop(i)
        self._spawn_sniper(cam)

    # ------------------------------------------------------------ 命中

    def register_hit(self):
        self.hits += 1

    def remove(self, t: Target):
        if t in self.targets:
            self.targets.remove(t)
        if self.mode == "botz":
            self.pending.append(C.RESPAWN_DELAY)
        elif self.mode == "reflex":
            self.spawn_timer = 0.08
        elif self.mode == "sniper":
            self.pending.append(C.RESPAWN_DELAY * 1.6)
