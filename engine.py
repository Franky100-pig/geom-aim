"""伪 3D 射线渲染引擎：地图、相机、投影、墙体光栅化、精灵可见性。

整个渲染的数学前提（改代码前先看这段，不然容易改崩）：

* 世界是二维网格，y 轴向下（南）。
* 相机方向 dir = (cos yaw, sin yaw)；右方向 plane_unit = (-sin yaw, cos yaw)。
* 屏幕上一根射线写成  ray = dir + plane_unit * s，s ∈ [-L, L]，L = tan(hFOV/2)。
  这样 dir 分量恒为 1，DDA 求出的参数 t 天然就是「垂直距离」，不会有鱼眼。
* 竖直方向：某个世界高度 h（0=地板，1=天花板）在深度 d 处的屏幕纵坐标
      y = horizon + (H * vscale / d) * (EYE_HEIGHT - h)
  其中 vscale = W / (2 * L * H)，这个取值保证横竖方向的「像素 / 世界单位」相等。
* pitch（上下看）在地平线里体现：horizon = H/2 + pitch_px。
"""

from __future__ import annotations

import math
import random
from collections import deque

import pygame

import config as C

NEAR = 0.05


# ---------------------------------------------------------------- 工具

def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def lerp_rgb(c1, c2, t: float):
    t = 0.0 if t < 0 else (1.0 if t > 1 else t)
    return (
        int(lerp(c1[0], c2[0], t)),
        int(lerp(c1[1], c2[1], t)),
        int(lerp(c1[2], c2[2], t)),
    )


def scale_rgb(c, f: float):
    return (
        min(255, int(c[0] * f)),
        min(255, int(c[1] * f)),
        min(255, int(c[2] * f)),
    )


def clamp(v, lo, hi):
    return lo if v < lo else (hi if v > hi else v)


def cell_height(v: int) -> float:
    """格子的实体高度（世界单位；1.0 = 一层楼 = 满高墙）。0 = 空地。

    半高箱矮于这个高度，所以视线和子弹只要高过箱顶就能飞过去 ——
    "蹲下藏得住、站着露头、跳起来能 peek" 全靠这一个数。
    """
    if v == C.CELL_LOW_BOX:
        return C.BOX_LOW_H
    if v == C.CELL_TALL_BOX:
        return C.BOX_TALL_H
    return 1.0 if v else 0.0


# ---------------------------------------------------------------- 地图

class GridMap:
    """0 = 空地，1 = 普通墙，2 = 强调柱。"""

    def __init__(self, grid, hmap=None):
        self.g = grid
        self.h = len(grid)
        self.w = len(grid[0])
        # 高度图：每个格中心的地面高度（世界单位，墙高 = 1.0）。
        # None 表示完全平整 —— h_at 恒返回 0，所有地形相关逻辑自动退化为旧行为。
        self.hmap = hmap

    def at(self, ix, iy):
        if 0 <= ix < self.w and 0 <= iy < self.h:
            return self.g[iy][ix]
        return 1

    def h_at(self, x: float, y: float) -> float:
        """世界坐标 (x, y) 处的地面高度，双线性插值。无高度图时恒为 0。"""
        if self.hmap is None:
            return 0.0
        fx = clamp(x - 0.5, 0.0, self.w - 1.0001)
        fy = clamp(y - 0.5, 0.0, self.h - 1.0001)
        ix, iy = int(fx), int(fy)
        tx, ty = fx - ix, fy - iy
        h = self.hmap
        v00 = h[iy][ix]
        v10 = h[iy][ix + 1] if ix + 1 < self.w else h[iy][ix]
        v01 = h[iy + 1][ix] if iy + 1 < self.h else h[iy][ix]
        v11 = (h[iy + 1][ix + 1]
               if (ix + 1 < self.w and iy + 1 < self.h) else h[iy][ix])
        return ((v00 * (1 - tx) + v10 * tx) * (1 - ty)
                + (v01 * (1 - tx) + v11 * tx) * ty)

    def blocked(self, fx: float, fy: float, r: float) -> bool:
        """圆 (fx, fy, r) 是否和任一墙格相交。"""
        for iy in range(int(fy - r) - 1, int(fy + r) + 2):
            for ix in range(int(fx - r) - 1, int(fx + r) + 2):
                if self.at(ix, iy) == 0:
                    continue
                nx = min(max(fx, ix), ix + 1)
                ny = min(max(fy, iy), iy + 1)
                dx, dy = fx - nx, fy - ny
                if dx * dx + dy * dy < r * r:
                    return True
        return False

    def clear_line(self, x0, y0, x1, y1) -> bool:
        """两点之间是否没有墙（视线判定）。"""
        dx, dy = x1 - x0, y1 - y0
        dist = math.hypot(dx, dy)
        if dist < 1e-6:
            return True
        steps = int(dist * 6) + 1
        sx, sy = dx / steps, dy / steps
        x, y = x0, y0
        for _ in range(steps):
            if self.at(int(x), int(y)):
                return False
            x += sx
            y += sy
        return True

    def terrain_occludes(self, x0, y0, z0, x1, y1, z1) -> bool:
        """纯地形遮挡（不管墙）：视线中途低于地面高度 → 被山坡挡住。

        用于精灵（人/靶）的可见性判定，和 clear_line_h 的地形段共用同一套
        高度场逻辑；墙的遮挡交给渲染器的 zbuf，这里不重复算。
        """
        if self.hmap is None:
            return False
        dx, dy = x1 - x0, y1 - y0
        dist = math.hypot(dx, dy)
        if dist < 1e-6:
            return False
        steps = int(dist * 6) + 1
        for i in range(1, steps + 1):
            t = i / steps
            zh = z0 + (z1 - z0) * t
            if zh < self.h_at(x0 + dx * t, y0 + dy * t) - 1e-6:
                return True
        return False

    def clear_line_h(self, x0, y0, z0, x1, y1, z1, g0: float = 0.0,
                     g1: float = 0.0) -> bool:
        """高度感知视线：从 (x0,y0,z0) 看向 (x1,y1,z1)。

        满高格子（墙/柱/高箱）一律挡住，和原来的 clear_line 一致；
        半高箱只在视线低于箱顶时才挡 —— 于是"蹲下藏得住、站着露头"。
        z0/z1 是"离地高度"，g0/g1 是两端的地面高度（地形）；两者相加才是
        绝对高度。无地形（g0=g1=0 且 hmap=None）时与旧行为逐像素一致。

        地形遮挡：视线中途低于该处地面高度 → 被山坡/山脊挡住，洼地能藏人。
        """
        z0 += g0
        z1 += g1
        dx, dy = x1 - x0, y1 - y0
        dist = math.hypot(dx, dy)
        if dist < 1e-6:
            return True
        steps = int(dist * 6) + 1
        for i in range(1, steps + 1):
            t = i / steps
            px, py = x0 + dx * t, y0 + dy * t
            zh = z0 + (z1 - z0) * t
            if self.hmap is not None and zh < self.h_at(px, py) - 1e-6:
                return False
            v = self.at(int(px), int(py))
            if not v:
                continue
            h = cell_height(v)
            if h >= 1.0:                       # 满高：照旧一定挡
                return False
            if zh < h:                         # 视线从箱子下方穿过
                return False
        return True

    def clear_corridor(self, x0, y0, x1, y1, r: float) -> bool:
        """半径为 r 的圆能否沿直线从 (x0,y0) 走到 (x1,y1) 而不被墙卡住。

        比 clear_line 多了「身体半径」维度：只检查中轴线会漏掉门洞/柱子的边
        缘——一个圆贴着门洞下沿时，圆心射线可能穿过门洞，但身体会撞到门框，
        于是 AI 在门口卡死并无限重算路径。这里同时检查中轴线和两侧各偏移 r
        的平行线，三条都无墙才算能直穿。用于寻路「一步拉直」的剪枝。
        """
        dx, dy = x1 - x0, y1 - y0
        dist = math.hypot(dx, dy)
        if dist < 1e-6:
            return True
        ux, uy = dx / dist, dy / dist
        # 垂直于行进方向的偏移单位向量
        px, py = -uy, ux

        def line_clear(ox, oy) -> bool:
            steps = int(dist * 6) + 1
            for i in range(steps + 1):
                t = i / steps
                x = x0 + ox + ux * dist * t
                y = y0 + oy + uy * dist * t
                if self.at(int(x), int(y)):
                    return False
            return True

        return (line_clear(0, 0)
                and line_clear(px * r, py * r)
                and line_clear(-px * r, -py * r))

    def random_free(self, rng, pad: float = 1.6):
        """在空地里随机取一点（格子中心附近）。"""
        for _ in range(200):
            x = rng.uniform(pad, self.w - pad)
            y = rng.uniform(pad, self.h - pad)
            if not self.blocked(x, y, 0.55):
                return x, y
        return self.w * 0.5, self.h * 0.5

    def center_free(self, clearance: float = 0.7):
        """返回地图几何中心附近、有富余活动空间的可站立点（格子中心坐标）。

        拼接式地图的几何中心可能正好落在房间之间的共享墙上，所以要从中心
        由内向外逐环搜索，找到第一个既在空地、又不会被墙卡住的点。
        """
        cx, cy = self.w * 0.5, self.h * 0.5
        for rad in range(0, max(self.w, self.h)):
            bx, by = int(cx), int(cy)
            found = None
            for dx in range(-rad, rad + 1):
                for dy in range(-rad, rad + 1):
                    if max(abs(dx), abs(dy)) != rad:
                        continue    # 只看当前这一圈
                    x, y = bx + dx, by + dy
                    if 1 <= x < self.w - 1 and 1 <= y < self.h - 1 and self.at(x, y) == 0:
                        if not self.blocked(x + 0.5, y + 0.5, clearance):
                            found = (x + 0.5, y + 0.5)
                            break
                if found:
                    break
            if found:
                return found
        return cx, cy


# ---------------------------------------------------------------- 掩体生成

# 一簇掩体的形状（相对锚点的格子偏移）：从单格到 2×2，尺寸都控制在 3 格内，
# 保证不会一簇就把一个大房间切开。
COVER_SHAPES = (
    ((0, 0),),
    ((0, 0), (1, 0)),
    ((0, 0), (0, 1)),
    ((0, 0), (1, 0), (0, 1), (1, 1)),
    ((0, 0), (1, 0), (0, 1)),
    ((0, 0), (1, 0), (2, 0)),
    ((0, 0), (0, 1), (0, 2)),
)


def _free_connected(g, W: int, H: int) -> bool:
    """所有空地格是否连通（4 邻域，判据和 BFS 寻路的 at()==0 一致）。

    随机掩体最怕把某个角落封死，所以每放一簇都用这个兜底校验一次。
    """
    start = None
    total = 0
    for y in range(H):
        row = g[y]
        for x in range(W):
            if row[x] == 0:
                total += 1
                if start is None:
                    start = (x, y)
    if start is None:
        return True
    seen = {start}
    q = deque([start])
    while q:
        cx, cy = q.popleft()
        for nx, ny in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)):
            if 0 <= nx < W and 0 <= ny < H and g[ny][nx] == 0 and (nx, ny) not in seen:
                seen.add((nx, ny))
                q.append((nx, ny))
    return len(seen) == total


def _place_cover(g, W: int, H: int, rng: random.Random,
                 doors, spawn_cells, n_clusters: int) -> int:
    """随机撒掩体，成对写入 (x,y) 与其 180° 旋转像 (W-1-x, H-1-y)。

    因为是成对写入，两边地形绝对镜像 —— 谁都不占便宜。
    每簇放下后都做连通性校验，一旦封死区域就整簇回滚，
    所以随机地形永远不会生成走不通的图。返回实际放下的簇数。
    """
    forb = set()
    for (x, y) in doors:
        for dy in range(-C.COVER_DOOR_MARGIN, C.COVER_DOOR_MARGIN + 1):
            for dx in range(-C.COVER_DOOR_MARGIN, C.COVER_DOOR_MARGIN + 1):
                forb.add((x + dx, y + dy))
    for (x, y) in spawn_cells:
        for dy in range(-C.COVER_SPAWN_MARGIN, C.COVER_SPAWN_MARGIN + 1):
            for dx in range(-C.COVER_SPAWN_MARGIN, C.COVER_SPAWN_MARGIN + 1):
                forb.add((x + dx, y + dy))

    placed = []
    made = 0
    tries = 0
    while made < n_clusters and tries < C.COVER_MAX_TRIES:
        tries += 1
        shape = rng.choice(COVER_SHAPES)
        v = (C.CELL_TALL_BOX if rng.random() < C.COVER_TALL_RATIO
             else C.CELL_LOW_BOX)
        ax = rng.randrange(2, W - 2)
        ay = rng.randrange(2, H - 2)
        cells = [(ax + dx, ay + dy) for dx, dy in shape]
        mirror = [(W - 1 - x, H - 1 - y) for x, y in cells]
        # 锚点正好落在旋转中心时，像和自己重合，只放一次
        both = cells if cells == mirror else cells + mirror

        ok = True
        for (x, y) in both:
            if not (1 < x < W - 1 and 1 < y < H - 1) or g[y][x] != 0:
                ok = False
                break
            if (x, y) in forb:
                ok = False
                break
            for (px, py) in placed:
                if abs(px - x) < C.COVER_MIN_GAP and abs(py - y) < C.COVER_MIN_GAP:
                    ok = False
                    break
            if not ok:
                break
        if not ok:
            continue

        backup = [(x, y, g[y][x]) for (x, y) in both]
        for (x, y) in both:
            g[y][x] = v
        if _free_connected(g, W, H):
            placed.extend(both)
            made += 1
        else:
            for (x, y, old) in backup:
                g[y][x] = old
    return made


def build_arena(rx: int = C.ARENA_TILES_X, ry: int = C.ARENA_TILES_Y,
                room_w: int = C.ARENA_ROOM_W, room_h: int = C.ARENA_ROOM_H,
                rng: random.Random | None = None, cover: bool = False,
                terrain_amp: float | None = None,
                terrain_freq: float | None = None,
                terrain_seed: int | None = None) -> GridMap:
    """拼接式竞技场：把 rx × ry 个房间直接拼成一张大地图。

    每个房间内部空旷、四壁围合，相邻房间之间留一个门洞连通，
    外圈再封一圈外墙。整体远大于原来的单房间 —— 狙击能拉出长视线，
    走位也更自由。改 rx / ry 就是在调场地规模。

    cover=True 时用随机掩体（半高箱 / 高箱）代替固定的强调柱，并按 180°
    旋转对称成对生成 —— 每场都不一样，但两边绝对公平。cover=False（默认）
    保持原来的固定柱布局，行为与过去完全一致。
    """
    stride_x = room_w + 1   # 房间 + 其与右侧房间的 1 格共享墙
    stride_y = room_h + 1
    W = rx * stride_x + 1
    H = ry * stride_y + 1
    g = [[1] * W for _ in range(H)]

    def carve(x0, y0, x1, y1, v=0):
        for y in range(max(0, y0), min(H, y1 + 1)):
            for x in range(max(0, x0), min(W, x1 + 1)):
                g[y][x] = v

    # 每个房间内部挖空
    for iy in range(ry):
        for ix in range(rx):
            x0 = ix * stride_x + 1
            y0 = iy * stride_y + 1
            carve(x0, y0, x0 + room_w - 1, y0 + room_h - 1)

    # 门洞：相邻房间之间在共享墙中央开一个 DOOR 宽的口。
    # 中心取 i*stride + stride/2 —— 只有这个取法能让整张图严格 180° 旋转对称。
    # （原来写成 1 + room//2，差半格，转 180° 后会错开一格。）
    DOOR = 4
    doors = set()
    for iy in range(ry):
        for ix in range(rx - 1):
            wx = (ix + 1) * stride_x           # 竖向共享墙的 x
            my = int(iy * stride_y + stride_y * 0.5)
            carve(wx, my - DOOR // 2, wx, my + DOOR // 2)
            doors.update((wx, y)
                         for y in range(my - DOOR // 2, my + DOOR // 2 + 1))
    for iy in range(ry - 1):
        for ix in range(rx):
            wy = (iy + 1) * stride_y           # 横向共享墙的 y
            mx = int(ix * stride_x + stride_x * 0.5)
            carve(mx - DOOR // 2, wy, mx + DOOR // 2, wy)
            doors.update((x, wy)
                         for x in range(mx - DOOR // 2, mx + DOOR // 2 + 1))

    # 房间中心（同样用 stride/2 取法，保证对称）
    def room_center(ix, iy):
        return (int(ix * stride_x + stride_x * 0.5),
                int(iy * stride_y + stride_y * 0.5))

    if cover:
        # 出生点（对角两个房间）周围留空，免得开局被箱子卡住
        spawns = [room_center(0, 0), room_center(rx - 1, ry - 1)]
        n = min(C.COVER_MAX_CLUSTERS, int(rx * ry * C.COVER_CLUSTERS_PER_ROOM))
        _place_cover(g, W, H, rng or random.Random(), doors, spawns, n)
    else:
        # 固定强调柱（type 2）：横排两根 + 竖排两根，避开正中心和门洞。
        for iy in range(ry):
            for ix in range(rx):
                cx, cy = room_center(ix, iy)
                for dx, dy in ((-7, 0), (7, 0), (0, -5), (0, 5)):
                    px, py = cx + dx, cy + dy
                    if 1 < px < W - 1 and 1 < py < H - 1:
                        g[py][px] = 2

    gm = GridMap(g)
    # 把房间尺寸带在地图上，让出生点 / 区域逻辑能按"真实地图"算，
    # 而不是去读全局 ARENA_* 配置（对战地图比练习小，尺寸对不上会算错）。
    gm.tiles_x = rx
    gm.tiles_y = ry
    gm.room_w = room_w
    gm.room_h = room_h

    # 地形高度图：独立种子，不消耗 cover 的 rng 序列，保证两边可复现、互不干扰。
    amp = (C.TERRAIN_AMP if terrain_amp is None else terrain_amp)
    freq = (C.TERRAIN_FREQ if terrain_freq is None else terrain_freq)
    if amp > 0 and (rng is not None or C.TERRAIN_ENABLED):
        seed = (C.TERRAIN_SEED if terrain_seed is None else terrain_seed)
        hrng = random.Random(seed)
        gm.hmap = make_heightmap(W, H, hrng, amp, freq)
    return gm


def make_heightmap(w: int, h: int, rng: random.Random, amp: float,
                   freq: float) -> list:
    """平滑高度场（值噪声）。返回 h×w 的格高度列表；amp<=0 返回 None。

    做法：在 freq 频率的粗网格上撒均匀随机值，再双线性插值成连续起伏。
    地图最外圈强制为 0（粗网格边界行/列恒为 0），避免边缘出现悬空或峭壁。
    高度图与房间布局无关、两边对称生成，所以不会让某一边天然占高地。
    """
    if amp <= 0:
        return None
    gx = max(3, int(w * freq) + 2)
    gy = max(3, int(h * freq) + 2)
    # 粗网格随机值，边界行/列（index 0 与 gx/gy）固定为 0
    lat = [[0.0] * (gx + 1) for _ in range(gy + 1)]
    for jy in range(1, gy):
        for jx in range(1, gx):
            lat[jy][jx] = rng.uniform(-1.0, 1.0)
    out = [[0.0] * w for _ in range(h)]
    for y in range(h):
        for x in range(w):
            fx = x / max(1, w - 1) * (gx - 1)
            fy = y / max(1, h - 1) * (gy - 1)
            ix, iy = int(fx), int(fy)
            tx, ty = fx - ix, fy - iy
            v00 = lat[iy][ix];     v10 = lat[iy][ix + 1]
            v01 = lat[iy + 1][ix]; v11 = lat[iy + 1][ix + 1]
            top = v00 * (1 - tx) + v10 * tx
            bot = v01 * (1 - tx) + v11 * tx
            out[y][x] = (top * (1 - ty) + bot * ty) * amp
    return out


# ---------------------------------------------------------------- 相机

class Camera:
    def __init__(self, x=14.5, y=10.5, yaw=0.0):
        self.x = x
        self.y = y
        self.yaw = yaw          # 基础朝向（不含后坐力）
        self.pitch_px = 0.0     # 上下看，单位是屏幕像素
        self.eff_yaw = yaw      # 含后坐力的实际朝向
        self.eff_pitch_px = 0.0
        self.z = 0.0            # 离地高度（跳跃）；只影响投影，不影响碰撞

    def apply_recoil(self, recoil_yaw: float, recoil_px: float):
        self.eff_yaw = self.yaw + recoil_yaw
        self.eff_pitch_px = clamp(
            self.pitch_px + recoil_px,
            -C.PITCH_LIMIT * 2.0 * 720.0,
            C.PITCH_LIMIT * 2.0 * 720.0,
        )

    def dir(self):
        return math.cos(self.eff_yaw), math.sin(self.eff_yaw)

    def plane_unit(self):
        return -math.sin(self.eff_yaw), math.cos(self.eff_yaw)


# ---------------------------------------------------------------- DDA

def cast_ray(gmap: GridMap, px: float, py: float, rdx: float, rdy: float):
    """沿 (rdx, rdy) 投射，返回 (垂直距离, 命中面 0=x 1=y, 墙的类型)。"""
    map_x, map_y = int(px), int(py)
    delta_x = abs(1.0 / rdx) if abs(rdx) > 1e-9 else 1e30
    delta_y = abs(1.0 / rdy) if abs(rdy) > 1e-9 else 1e30

    if rdx < 0:
        step_x = -1
        side_x = (px - map_x) * delta_x
    else:
        step_x = 1
        side_x = (map_x + 1.0 - px) * delta_x

    if rdy < 0:
        step_y = -1
        side_y = (py - map_y) * delta_y
    else:
        step_y = 1
        side_y = (map_y + 1.0 - py) * delta_y

    side = 0
    cell = 1
    for _ in range(256):
        if side_x < side_y:
            side_x += delta_x
            map_x += step_x
            side = 0
        else:
            side_y += delta_y
            map_y += step_y
            side = 1
        v = gmap.at(map_x, map_y)
        if v:
            cell = v
            break

    if side == 0:
        perp = (map_x - px + (1 - step_x) * 0.5) / rdx
    else:
        perp = (map_y - py + (1 - step_y) * 0.5) / rdy
    if perp < NEAR:
        perp = NEAR
    return perp, side, cell


def cast_ray_layers(gmap: GridMap, px: float, py: float,
                    rdx: float, rdy: float, max_layers: int = 4):
    """沿射线收集"层"，近 → 远。半高箱不终止射线（能从它上方看过去），
    撞到满高格子才停。返回 [(距离, 命中面, 格子类型, 命中格x, 命中格y), ...]，
    至少一项。

    渲染用它把矮箱和它后面的东西分层画出来 —— 只有矮箱的话，你看到的
    是箱子挡住下半截、后面的人露出上半身。
    命中格坐标给地形用：墙脚要踩在该处的地面高度上（起伏地图）。
    """
    out = []
    map_x, map_y = int(px), int(py)
    delta_x = abs(1.0 / rdx) if abs(rdx) > 1e-9 else 1e30
    delta_y = abs(1.0 / rdy) if abs(rdy) > 1e-9 else 1e30

    if rdx < 0:
        step_x = -1
        side_x = (px - map_x) * delta_x
    else:
        step_x = 1
        side_x = (map_x + 1.0 - px) * delta_x

    if rdy < 0:
        step_y = -1
        side_y = (py - map_y) * delta_y
    else:
        step_y = 1
        side_y = (map_y + 1.0 - py) * delta_y

    side = 0
    for _ in range(256):
        if side_x < side_y:
            side_x += delta_x
            map_x += step_x
            side = 0
        else:
            side_y += delta_y
            map_y += step_y
            side = 1
        v = gmap.at(map_x, map_y)
        if not v:
            continue
        if side == 0:
            perp = (map_x - px + (1 - step_x) * 0.5) / rdx
        else:
            perp = (map_y - py + (1 - step_y) * 0.5) / rdy
        if perp < NEAR:
            perp = NEAR
        out.append((perp, side, v, map_x, map_y))
        if cell_height(v) >= 1.0 or len(out) >= max_layers:
            break

    if not out:
        out.append((1e9, 0, 0, 0, 0))
    return out


def cast_ray_block(gmap: GridMap, px: float, py: float, rdx: float, rdy: float,
                   eye: float, slope: float):
    """子弹被挡住的距离。弹道高度 h(d) = eye + slope·d。

    半高箱只挡住打向它高度以下的弹道（瞄头能越过箱子打中人）；
    满高的墙 / 柱 / 高箱一律挡住 —— 保持"墙一定挡子弹"的原有行为。
    """
    map_x, map_y = int(px), int(py)
    delta_x = abs(1.0 / rdx) if abs(rdx) > 1e-9 else 1e30
    delta_y = abs(1.0 / rdy) if abs(rdy) > 1e-9 else 1e30

    if rdx < 0:
        step_x = -1
        side_x = (px - map_x) * delta_x
    else:
        step_x = 1
        side_x = (map_x + 1.0 - px) * delta_x

    if rdy < 0:
        step_y = -1
        side_y = (py - map_y) * delta_y
    else:
        step_y = 1
        side_y = (map_y + 1.0 - py) * delta_y

    side = 0
    for _ in range(256):
        if side_x < side_y:
            side_x += delta_x
            map_x += step_x
            side = 0
        else:
            side_y += delta_y
            map_y += step_y
            side = 1
        v = gmap.at(map_x, map_y)
        if not v:
            continue
        # 命中面到相机的垂直距离（与 cast_ray 同一个公式）
        if side == 0:
            perp = (map_x - px + (1 - step_x) * 0.5) / rdx
        else:
            perp = (map_y - py + (1 - step_y) * 0.5) / rdy
        if perp < NEAR:
            perp = NEAR
        h = cell_height(v)
        if h >= 1.0:                       # 满高：一定挡
            return perp
        if eye + slope * perp < h:         # 弹道从箱子下方穿过 → 被挡
            return perp
        # 弹道高过箱顶 → 飞过去，继续往后找
    return 1e9


# ---------------------------------------------------------------- 渲染器

class Renderer:
    def __init__(self, w: int, h: int, hfov_deg: float):
        self.zbuf = []
        self.box_d = []
        self.box_y = []
        self.set_viewport(w, h, hfov_deg)

    # -- 视口与投影参数 ------------------------------------------------

    def set_viewport(self, w: int, h: int, hfov_deg: float):
        self.w = w
        self.h = h
        tan_h = math.tan(math.radians(hfov_deg) * 0.5)
        self.plane_len = tan_h
        self.vscale = w / (2.0 * tan_h * h)
        self.zoom = 1.0            # 开镜放大倍率；>1 即收窄 FOV。默认 1 不改变任何行为
        n = (w // C.RENDER_COL_STEP) + 2
        self.zbuf = [1e9] * n          # 最近满高墙的距离（精灵深度遮挡用）
        self.box_d = [1e9] * n         # 最近半高箱的距离
        self.box_y = [1e9] * n         # 该半高箱顶边在屏幕上的 y（精灵垂直裁剪用）
        self._build_gradients()

    @property
    def pl(self):
        """受 zoom 影响的有效横向平面长度（越小 FOV 越窄 = 画面越大）。"""
        return self.plane_len / self.zoom

    @property
    def vs(self):
        """受 zoom 影响的有效垂直缩放。

        注意是乘子：`vscale * zoom`。因为 vscale ∝ 1/FOV，FOV 收窄（zoom 进）
        时 vscale 反而变大、精灵/墙体在屏幕上更高。pl*vs 恒等于原 plane_len*vscale
        （= w/(2h)），保证横竖像素密度一致。
        """
        return self.vscale * self.zoom

    def set_zoom(self, z: float):
        self.zoom = max(0.1, float(z))

    def lerp_zoom(self, target: float, dt: float, rate: float = 14.0):
        """开镜/退出时平滑过渡，避免画面硬切。"""
        k = min(1.0, dt * rate)
        self.zoom += (max(0.1, target) - self.zoom) * k

    @staticmethod
    def _surface(w, h):
        """无头环境（测试）下 convert() 会抛错，这里兜一下。"""
        s = pygame.Surface((w, h))
        if pygame.display.get_init():
            s = s.convert()
        return s

    def _build_gradients(self):
        """一次性烤好天花板 / 地板的竖直渐变，之后每帧只做两次 blit。"""
        self.ceil_grad = self._surface(self.w, self.h)
        self.floor_grad = self._surface(self.w, self.h)
        last = max(1, self.h - 1)
        for i in range(self.h):
            t = i / last
            self.ceil_grad.fill(lerp_rgb(C.C_CEIL_TOP, C.C_CEIL_HORIZON, t),
                                (0, i, self.w, 1))
            self.floor_grad.fill(lerp_rgb(C.C_FLOOR_HORIZON, C.C_FLOOR_NEAR, t),
                                 (0, i, self.w, 1))

    def horizon(self, cam: Camera) -> float:
        return self.h * 0.5 + cam.eff_pitch_px

    def eye_h(self, cam: Camera) -> float:
        """当前眼高（世界单位）。基准 EYE_HEIGHT，跳跃时再加上相机的 z。"""
        return C.EYE_HEIGHT + cam.z

    def pixels_per_unit(self, depth: float) -> float:
        return self.h * self.vs / max(depth, NEAR)

    def project(self, cam: Camera, wx: float, wy: float, world_h: float):
        """世界点 → 屏幕。返回 (sx, sy, depth)，相机背后返回 None。"""
        dx, dy = cam.dir()
        pux, puy = cam.plane_unit()
        rx, ry = wx - cam.x, wy - cam.y
        depth = rx * dx + ry * dy
        if depth <= NEAR:
            return None
        lateral = rx * pux + ry * puy
        sx = self.w * 0.5 * (1.0 + lateral / (depth * self.pl))
        eye = self.eye_h(cam)
        sy = self.horizon(cam) + (self.h * self.vs / depth) * (eye - world_h)
        return sx, sy, depth

    def aim_height(self, cam: Camera, depth: float) -> float:
        """准星（屏幕正中）在给定深度处指向的世界高度。"""
        return self.eye_h(cam) + cam.eff_pitch_px * depth / (self.h * self.vs)

    def screen_to_pixels_pitch(self, angle: float) -> float:
        """把垂直视角（弧度）换算成地平线像素偏移。"""
        return angle * self.h * self.vs

    # -- 背景 ----------------------------------------------------------

    def draw_sky_floor(self, surf: pygame.Surface, cam: Camera):
        hz = self.horizon(cam)
        surf.blit(self.ceil_grad, (0, int(hz) - self.h))
        surf.blit(self.floor_grad, (0, int(hz)))

    # -- 地板网格 ------------------------------------------------------

    def _world_line_screen(self, cam, ax, ay, bx, by, near=0.35,
                           ga: float = 0.0, gb: float = 0.0):
        dx, dy = cam.dir()
        da = (ax - cam.x) * dx + (ay - cam.y) * dy
        db = (bx - cam.x) * dx + (by - cam.y) * dy
        t0, t1 = 0.0, 1.0
        delta = db - da
        if abs(delta) < 1e-9:
            if da < near:
                return None
        elif delta > 0:
            t0 = max(t0, (near - da) / delta)
            if t0 >= 1.0:
                return None
        else:
            t1 = min(t1, (near - da) / delta)
            if t1 <= 0.0:
                return None
        if t0 >= t1:
            return None
        pa = self.project(cam, ax + (bx - ax) * t0, ay + (by - ay) * t0,
                          ga + (gb - ga) * t0)
        pb = self.project(cam, ax + (bx - ax) * t1, ay + (by - ay) * t1,
                          ga + (gb - ga) * t1)
        if pa is None or pb is None:
            return None
        return (pa[0], pa[1]), (pb[0], pb[1])

    def draw_floor_grid(self, surf: pygame.Surface, cam: Camera, gmap: GridMap, radius=22.0):
        x0 = max(0, int(cam.x - radius))
        x1 = min(gmap.w, int(cam.x + radius) + 1)
        y0 = max(0, int(cam.y - radius))
        y1 = min(gmap.h, int(cam.y + radius) + 1)
        hz = self.horizon(cam)
        has_h = gmap.hmap is not None
        for gx in range(x0, x1 + 1):
            seg = self._world_line_screen(
                cam, gx, y0, gx, y1,
                ga=gmap.h_at(gx + 0.5, y0 + 0.5) if has_h else 0.0,
                gb=gmap.h_at(gx + 0.5, y1 + 0.5) if has_h else 0.0)
            if seg:
                pygame.draw.line(surf, C.C_GRID, seg[0], seg[1])
        for gy in range(y0, y1 + 1):
            seg = self._world_line_screen(
                cam, x0, gy, x1, gy,
                ga=gmap.h_at(x0 + 0.5, gy + 0.5) if has_h else 0.0,
                gb=gmap.h_at(x1 + 0.5, gy + 0.5) if has_h else 0.0)
            if seg:
                pygame.draw.line(surf, C.C_GRID, seg[0], seg[1])
        # 地平线本身给一条细亮线，强化空间感
        if -20 < hz < self.h + 20:
            pygame.draw.line(surf, lerp_rgb(C.C_GRID, C.C_ACCENT, 0.35),
                             (0, hz), (self.w, hz))

    # -- 墙体 ----------------------------------------------------------

    def render_walls(self, surf: pygame.Surface, cam: Camera, gmap: GridMap):
        dx, dy = cam.dir()
        pux, puy = cam.plane_unit()
        step = C.RENDER_COL_STEP
        w, h, L = self.w, self.h, self.pl
        hz = self.horizon(cam)
        eye_h = self.eye_h(cam)     # 跳跃会抬高眼高，墙面上下沿跟着走
        cols = w // step + 1
        if len(self.zbuf) != cols:
            self.zbuf = [1e9] * cols
            self.box_d = [1e9] * cols
            self.box_y = [1e9] * cols
        zbuf, box_d, box_y = self.zbuf, self.box_d, self.box_y
        fog_k = 0.055

        for ci in range(cols):
            sx = ci * step
            camx = 2.0 * (sx + step * 0.5) / w - 1.0
            rdx = dx + pux * (camx * L)
            rdy = dy + puy * (camx * L)
            layers = cast_ray_layers(gmap, cam.x, cam.y, rdx, rdy)

            # —— 先按 近→远 记账：最近的全高墙进 zbuf，最近的矮箱记遮挡上沿 ——
            zbuf[ci] = 1e9
            box_d[ci] = 1e9
            box_y[ci] = 1e9
            for dist, _side, cell, _hx, _hy in layers:
                if dist >= 1e9:
                    break
                hh = cell_height(cell)
                line_h = h * self.vs / dist
                ground = gmap.h_at(_hx + 0.5, _hy + 0.5) if gmap.hmap else 0.0
                y_top = hz + line_h * (eye_h - ground - hh)
                if hh >= 1.0:
                    if zbuf[ci] >= 1e9:
                        zbuf[ci] = dist
                    break                      # 满高，后面看不见了
                if box_d[ci] >= 1e9:
                    box_d[ci] = dist
                    box_y[ci] = y_top

            # —— 再按 远→近 画，近的盖住远的；矮箱只画自己那截 ——
            for dist, side, cell, hx, hy in reversed(layers):
                if dist >= 1e9:
                    continue
                line_h = h * self.vs / dist
                hh = cell_height(cell)
                ground = gmap.h_at(hx + 0.5, hy + 0.5) if gmap.hmap else 0.0
                top = hz + line_h * (eye_h - ground - hh)
                bot = hz + line_h * (eye_h - ground)
                y0 = int(top)
                y1 = int(bot) + 1
                if y1 <= 0 or y0 >= h:
                    continue
                if y0 < 0:
                    y0 = 0
                if y1 > h:
                    y1 = h
                if y1 <= y0:
                    continue

                if cell == C.CELL_LOW_BOX:
                    base = C.C_BOX_LOW_SIDE if side else C.C_BOX_LOW
                elif cell == C.CELL_TALL_BOX:
                    base = C.C_BOX_TALL_SIDE if side else C.C_BOX_TALL
                elif cell == 2:
                    base = C.C_WALL_ACC_SIDE if side else C.C_WALL_ACC
                else:
                    base = C.C_WALL_SIDE if side else C.C_WALL
                f = clamp(1.16 - dist * fog_k, 0.26, 1.0)
                pygame.draw.rect(surf, scale_rgb(base, f), (sx, y0, step, y1 - y0))

    # -- 精灵（靶子）---------------------------------------------------

    def sprite_geom(self, cam: Camera, wx: float, wy: float, bot_h: float, bot_w: float,
                    ground_z: float = 0.0):
        """返回 (中心 x, 脚底 y, 高 px, 宽 px, 深度)，不可见返回 None。

        ground_z 是脚下地形高度：人/靶站在山坡上，脚底会抬高到对应世界高度，
        渲染出来的小人就"踩"在地形上而不是浮空。
        """
        r = self.project(cam, wx, wy, ground_z)
        if r is None:
            return None
        sx, sy, depth = r
        if depth < 0.30:
            return None
        ppu = self.h * self.vs / depth
        return sx, sy, bot_h * ppu, bot_w * ppu, depth

    def visible_runs(self, x0: float, x1: float, depth: float, max_runs: int = 4):
        """在 [x0, x1] 范围内，找出没有被满高墙挡住的连续横向区间。

        返回 [(左, 右, 遮挡上沿 y)]。y 是这一段里最近的半高箱顶边在屏幕上的
        位置 —— 精灵只画 y 以上的部分（y=None 表示这段没有矮箱挡着）。
        有了它，"蹲在半高箱后面完全藏住 / 站着露头"才成立。
        """
        step = C.RENDER_COL_STEP
        i0 = max(0, int(x0) // step)
        i1 = min(len(self.zbuf) - 1, int(x1) // step)
        if i1 < i0:
            return []
        runs = []
        start = None
        top = None
        for i in range(i0, i1 + 1):
            if depth < self.zbuf[i]:
                if start is None:
                    start = i
                    top = None
                if self.box_d[i] < depth:
                    y = self.box_y[i]
                    top = y if top is None else min(top, y)
            elif start is not None:
                runs.append((start * step, i * step, top))
                start = None
                top = None
                if len(runs) >= max_runs:
                    break
        if start is not None and len(runs) < max_runs:
            runs.append((start * step, (i1 + 1) * step, top))
        return [(a, b, t) for a, b, t in runs if b > a]
