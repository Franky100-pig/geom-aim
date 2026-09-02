"""烟雾弹：投掷物理 + 真实封烟。

设计要点：
* 烟是**真封视线**的 —— AI 看不见烟里/烟外的目标，渲染也跟着藏人。
  但**子弹照穿**（跟 CS 一样）：封的是信息，不是火力。
* 一颗弹分两段生命：先当刚体飞（抛物线 + 落地弹跳 + 撞墙反弹 + 摩擦停下），
  引信到了就地起一团烟，烟心锚定在起烟那一刻的位置，之后弹体继续滑到停稳
  （所以你会看到烟冒出来、弹壳还往前滚一点，跟真实情况一致）。
* SmokeField 只管模拟，不管"你还有几颗 / 多久能再扔"——那是 Game 的事。
"""

from __future__ import annotations

import math

import pygame

import config as C

# 烟团在竖直方向上的中心高度（世界单位，墙高 = 1.0）
CLOUD_CENTER_H = 0.45

_BLOB_CACHE: dict[tuple, pygame.Surface] = {}


def _blob(color, size: int = 96) -> pygame.Surface:
    """预渲染一团软边圆形烟（径向衰减），之后只做缩放，避免每帧逐像素。"""
    key = (color, size)
    hit = _BLOB_CACHE.get(key)
    if hit is not None:
        return hit
    s = pygame.Surface((size, size), pygame.SRCALPHA)
    c = size / 2.0
    for y in range(size):
        for x in range(size):
            d = math.hypot(x + 0.5 - c, y + 0.5 - c) / c
            if d >= 1.0:
                continue
            a = int(235 * (1.0 - d) ** 1.5)
            s.set_at((x, y), (color[0], color[1], color[2], a))
    _BLOB_CACHE[key] = s
    return s


def _seg_circle(x0, y0, x1, y1, cx, cy, r) -> bool:
    """线段 (x0,y0)-(x1,y1) 是否穿过圆 (cx,cy,r)。"""
    dx, dy = x1 - x0, y1 - y0
    l2 = dx * dx + dy * dy
    if l2 < 1e-9:
        return math.hypot(cx - x0, cy - y0) <= r
    t = ((cx - x0) * dx + (cy - y0) * dy) / l2
    t = 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)
    px, py = x0 + dx * t, y0 + dy * t
    return math.hypot(cx - px, cy - py) <= r


class SmokeGrenade:
    """一颗烟雾弹。起烟前是刚体，起烟后只剩一团会长大/消散的烟。"""

    def __init__(self, x: float, y: float, z: float,
                 vx: float, vy: float, vz: float, team: int = 0):
        self.x, self.y, self.z = x, y, z
        self.vx, self.vy, self.vz = vx, vy, vz
        self.team = team            # 投掷者所属队伍（用于"非友伤"判定）
        self.t = 0.0                # 出手后经过的时间
        self.resting = False        # 已经停稳
        self.done = False           # 烟已散尽，可以回收
        self._popped = False
        self.hit_ids = set()        # 飞行中已直击过的 Agent id（避免一帧多次扣血）
        self.cloud_x, self.cloud_y = x, y
        self._r = 0.0

    # ------------------------------------------------------------ 查询

    @property
    def cloud_r(self) -> float:
        """当前烟半径；0 表示还没起烟或已散尽。"""
        return self._r

    @property
    def smoking(self) -> bool:
        return self._r > 0.0

    @property
    def density(self) -> float:
        """0~1 的浓度，用来控制渲染透明度。"""
        if self._r <= 0.0:
            return 0.0
        return min(1.0, self._r / C.SMOKE_RADIUS)

    # ------------------------------------------------------------ 推进

    def update(self, dt: float, gmap):
        self.t += dt
        # 弹体一直模拟到停稳为止（起烟后还在地上滚一会儿，看着更真）
        if not self.resting:
            self._step_flight(dt, gmap)
        if not self._popped and self.t >= C.SMOKE_FUSE:
            self._pop()
        self._step_cloud()

    def _pop(self):
        self._popped = True
        self.cloud_x, self.cloud_y = self.x, self.y

    def _step_flight(self, dt: float, gmap):
        self.vz -= C.SMOKE_GRAVITY * dt
        self.z += self.vz * dt
        if self.z <= 0.0:
            self.z = 0.0
            if abs(self.vz) > 0.6:
                self.vz = -self.vz * C.SMOKE_BOUNCE
            else:
                self.vz = 0.0

        # 水平分轴推进，撞墙就反弹（不会卡进墙里）
        nx = self.x + self.vx * dt
        if gmap.blocked(nx, self.y, 0.12):
            self.vx = -self.vx * C.SMOKE_WALL_BOUNCE
        else:
            self.x = nx
        ny = self.y + self.vy * dt
        if gmap.blocked(self.x, ny, 0.12):
            self.vy = -self.vy * C.SMOKE_WALL_BOUNCE
        else:
            self.y = ny

        # 只有贴地才明显衰减（空中保留惯性）
        if self.z <= 1e-6:
            f = max(0.0, 1.0 - C.SMOKE_FRICTION * dt)
            self.vx *= f
            self.vy *= f

        if (self.z <= 1e-6 and self.vz == 0.0
                and math.hypot(self.vx, self.vy) < 0.12):
            self.vx = self.vy = self.vz = 0.0
            self.resting = True

    def _step_cloud(self):
        if not self._popped:
            self._r = 0.0
            return
        t = self.t - C.SMOKE_FUSE
        grow, hold, fade = C.SMOKE_GROW, C.SMOKE_HOLD, C.SMOKE_FADE
        if t <= 0.0:
            self._r = 0.0
        elif t < grow:
            self._r = C.SMOKE_RADIUS * (t / grow)
        elif t < grow + hold:
            self._r = C.SMOKE_RADIUS
        elif t < grow + hold + fade:
            k = (t - grow - hold) / fade
            self._r = C.SMOKE_RADIUS * max(0.0, 1.0 - k)
        else:
            self._r = 0.0
            self.done = True


class SmokeField:
    """场上的所有烟雾弹。只管模拟与渲染，弹药/冷却由调用方管。"""

    def __init__(self):
        self.grenades: list[SmokeGrenade] = []

    # ------------------------------------------------------------ 增删

    def throw(self, x: float, y: float, z: float,
              dx: float, dy: float,
              speed: float | None = None,
              up: float | None = None,
              team: int = 0) -> SmokeGrenade | None:
        """从 (x,y,z) 朝 (dx,dy) 扔一颗。场上满了就拒绝（返回 None）。"""
        live = sum(1 for g in self.grenades if not g.done)
        if live >= C.SMOKE_MAX_ACTIVE:
            return None
        n = math.hypot(dx, dy)
        if n < 1e-6:
            return None
        ux, uy = dx / n, dy / n
        sp = C.SMOKE_THROW_SPEED if speed is None else speed
        g = SmokeGrenade(x, y, max(z, 0.05), ux * sp, uy * sp,
                         C.SMOKE_THROW_UP if up is None else up, team=team)
        self.grenades.append(g)
        return g

    def plant(self, x: float, y: float, radius: float | None = None) -> SmokeGrenade:
        """调试/测试用：直接在某处放一团满烟（下一帧起按 SMOKE_RADIUS 走）。"""
        g = SmokeGrenade(x, y, 0.0, 0.0, 0.0, 0.0, team=0)
        g.cloud_x, g.cloud_y = x, y
        g.t = C.SMOKE_FUSE + C.SMOKE_GROW
        g._popped = True
        g.resting = True
        g._r = C.SMOKE_RADIUS if radius is None else radius
        self.grenades.append(g)
        return g

    def clear(self):
        self.grenades.clear()

    # ------------------------------------------------------------ 查询

    def blocks(self, x0: float, y0: float, x1: float, y1: float) -> bool:
        """这条视线是否被烟挡住（只看烟，不管墙）。"""
        for g in self.grenades:
            if g._r <= 0.0:
                continue
            if _seg_circle(x0, y0, x1, y1, g.cloud_x, g.cloud_y, g._r):
                return True
        return False

    def hides(self, x: float, y: float) -> bool:
        """这个点是否藏在一团烟里（渲染时用来藏人）。"""
        for g in self.grenades:
            if g._r <= 0.0:
                continue
            if math.hypot(x - g.cloud_x, y - g.cloud_y) <= g._r:
                return True
        return False

    # ------------------------------------------------------------ 推进

    def update(self, dt: float, gmap):
        for g in self.grenades:
            g.update(dt, gmap)
        if any(g.done for g in self.grenades):
            self.grenades = [g for g in self.grenades if not g.done]

    # ------------------------------------------------------------ 绘制

    def draw(self, surf: pygame.Surface, renderer, cam):
        """从远到近画烟团。飞行中的弹体画成一个小亮点。"""
        def key(g: SmokeGrenade):
            return -((g.cloud_x - cam.x) ** 2 + (g.cloud_y - cam.y) ** 2)

        for g in sorted(self.grenades, key=key):
            if g._r > 0.0:
                self.draw_cloud(surf, renderer, cam, g)
            elif not g.resting:
                self.draw_body(surf, renderer, cam, g)

    def draw_cloud(self, surf, renderer, cam, g: SmokeGrenade):
        proj = renderer.project(cam, g.cloud_x, g.cloud_y, CLOUD_CENTER_H)
        if proj is None:
            return
        sx, sy, depth = proj
        # 世界单位 → 屏幕像素（竖直方向每单位多少像素）
        px_per_unit = renderer.h * renderer.vs / depth
        rad = g._r * px_per_unit
        if rad < 1.0:
            return
        size = int(rad * 2.0)
        if size > 4000:
            return

        blob = _blob(C.C_SMOKE)
        img = pygame.transform.smoothscale(blob, (size, size))
        img = img.copy()
        img.set_alpha(int(235 * g.density))
        surf.blit(img, (sx - rad, sy - rad))

    def draw_body(self, surf, renderer, cam, g: SmokeGrenade):
        proj = renderer.project(cam, g.x, g.y, g.z + 0.06)
        if proj is None:
            return
        sx, sy, depth = proj
        rad = max(2.0, 0.09 * renderer.h * renderer.vs / depth)
        pygame.draw.circle(surf, C.C_SMOKE, (int(sx), int(sy)), int(rad))
        pygame.draw.circle(surf, C.C_WARN, (int(sx), int(sy)), int(rad), 1)
