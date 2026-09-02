"""GEOM AIM 的核心自检：投影数学、射线、命中判定、无头冒烟。

直接跑：  python3 tests/test_core.py
"""

from __future__ import annotations

import math
import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pygame  # noqa: E402

import config as C  # noqa: E402
import hud  # noqa: E402
from engine import Camera, GridMap, Renderer, build_arena, cast_ray  # noqa: E402
from targets import MODE_KEYS, Range, Target  # noqa: E402

PASS, FAIL = [], []


def check(name: str, cond: bool, detail: str = ""):
    (PASS if cond else FAIL).append(name)
    mark = "  ok  " if cond else " FAIL "
    print(f"[{mark}] {name}" + (f"   -> {detail}" if detail else ""))


def close(a, b, tol=1e-6):
    return abs(a - b) <= tol


# ---------------------------------------------------------------- 地图

def test_map():
    g = build_arena()
    check("地图每行等宽", all(len(row) == g.w for row in g.g), f"{g.w}x{g.h}")
    check("外墙封闭",
          all(g.at(x, 0) == 1 and g.at(x, g.h - 1) == 1 for x in range(g.w))
          and all(g.at(0, y) == 1 and g.at(g.w - 1, y) == 1 for y in range(g.h)))
    spawn = g.center_free()
    check("出生点在可站立处", not g.blocked(spawn[0], spawn[1], C.PLAYER_RADIUS),
          f"{spawn}")
    check("出生点确实在空地", g.at(int(spawn[0]), int(spawn[1])) == 0)
    check("墙格判定为阻挡", g.blocked(0.5, 0.5, 0.1))
    # 出生点到自身连线通畅（空地内）
    check("空地连线通畅", g.clear_line(spawn[0], spawn[1], spawn[0], spawn[1] + 0.01))
    # 找一面外墙，验证从出生点打到它会经过墙体被挡住
    wall = (0, 0)
    for y in range(g.h):
        if g.at(0, y) == 1:
            wall = (0, y)
            break
    check("穿墙连线被挡", not g.clear_line(spawn[0], spawn[1], wall[0] + 0.5, wall[1] + 0.5))
    # 拼接式：整体比单个房间大，且内部有房间掩体柱（type 2）
    check("由多个房间拼接（比单房间大）",
          g.w >= C.ARENA_TILES_X * (C.ARENA_ROOM_W + 1) + 1)
    check("房间内有掩体柱", any(g.at(x, y) == 2
                                for y in range(g.h) for x in range(g.w)))


# ---------------------------------------------------------------- 字体

def _ink(f, s: str) -> int:
    """渲染字符串后统计不透明像素数（缺字会渲染成空白或统一方框）。"""
    return pygame.mask.from_surface(f.render(s, True, (255, 255, 255))).count()


def test_font():
    f = hud.font(24)
    check("字体对象能创建", f is not None)
    check("CJK 字体加载成功（非兜底）", hud._font_path is not None,
          hud._font_path or "退到了 pygame 默认字体，中文会变豆腐块")

    check("ASCII 有字形", _ink(f, "A") > 0, f"{_ink(f, 'A')} px")
    check("汉字有字形", _ink(f, "枪") > 0, f"{_ink(f, '枪')} px")

    # 关键判据：不同汉字笔画数不同。若字体缺字、统一回退到 .notdef 方框，
    # 每个字的墨迹像素数会完全一样。
    sample = "枪靶练模菜准星灵敏度开关"
    inks = [_ink(f, ch) for ch in sample]
    distinct = len(set(inks))
    check("汉字字形互不相同（非缺字方框）", distinct >= 6,
          f"{distinct}/{len(sample)} 种不同墨迹")

    # 私用区字符几乎必定缺字，拿它当缺字基准
    priv = _ink(f, "\ue000")
    check("汉字不同于缺字回退", _ink(f, "枪") != priv or priv == 0,
          f"枪={_ink(f, '枪')} 缺字基准={priv}")

    for s in ("练枪房 / aim trainer", "鼠标灵敏度", "切换准星样式"):
        check(f"菜单文本可渲染：{s[:5]}…", _ink(f, s) > 0)


# ---------------------------------------------------------------- 投影

def test_projection():
    r = Renderer(1280, 720, 90.0)
    cam = Camera(14.5, 10.5, 0.0)     # 朝东
    cam.apply_recoil(0.0, 0.0)
    hz = r.horizon(cam)
    check("地平线在屏幕中央", close(hz, 360.0), f"{hz}")

    # 正前方 10 米 → 屏幕正中
    p = r.project(cam, cam.x + 10.0, cam.y, 0.5)
    check("正前方点落在屏幕中心", p is not None and close(p[0], 640.0, 1e-6), f"{p and p[0]}")
    check("眼高投影落在地平线", p is not None and close(p[1], hz, 1e-6))

    # 右手边（朝东时右手边是 +y）
    pr = r.project(cam, cam.x + 10.0, cam.y + 2.0, 0.5)
    check("右侧点投影在中心右边", pr[0] > 640.0, f"{pr[0]:.1f}")
    pl = r.project(cam, cam.x + 10.0, cam.y - 2.0, 0.5)
    check("左侧点投影在中心左边", pl[0] < 640.0, f"{pl[0]:.1f}")
    check("左右对称", close(pr[0] - 640.0, 640.0 - pl[0], 1e-6))

    # 地板在下、天花板在上
    floor = r.project(cam, cam.x + 10.0, cam.y, 0.0)
    ceil = r.project(cam, cam.x + 10.0, cam.y, 1.0)
    check("地板在地平线下方", floor[1] > hz)
    check("天花板在地平线上方", ceil[1] < hz)

    # 越远越靠近地平线
    near = r.project(cam, cam.x + 3.0, cam.y, 0.0)
    far = r.project(cam, cam.x + 20.0, cam.y, 0.0)
    check("远处地板更贴近地平线", far[1] < near[1] and far[1] > hz)

    # 正方形像素：横竖比例必须一致
    check("横竖像素密度一致",
          close(r.w / (2.0 * r.plane_len), r.h * r.vscale, 1e-9),
          f"{r.w / (2 * r.plane_len):.4f} vs {r.h * r.vscale:.4f}")

    # 背后的点不投影
    check("背后不投影", r.project(cam, cam.x - 10.0, cam.y, 0.5) is None)

    # pitch：抬头时准星指向更高的世界高度
    check("平视时准星在眼高", close(r.aim_height(cam, 10.0), C.EYE_HEIGHT))
    cam.eff_pitch_px = 28.0
    h10 = r.aim_height(cam, 10.0)
    h5 = r.aim_height(cam, 5.0)
    check("抬头后准星高于眼高", h10 > C.EYE_HEIGHT, f"{h10:.3f}")
    check("同一俯仰下近处抬升更少", h5 < h10, f"{h5:.3f} < {h10:.3f}")
    cam.eff_pitch_px = 0.0


# ---------------------------------------------------------------- 射线

def test_raycast():
    g = GridMap([[1, 1, 1],
                 [1, 0, 1],
                 [1, 1, 1]])
    d, side, cell = cast_ray(g, 1.5, 1.5, 1.0, 0.0)
    check("正东打墙距离正确", close(d, 0.5, 1e-6), f"{d}")
    d2, _, _ = cast_ray(g, 1.5, 1.5, 0.0, 1.0)
    check("正南打墙距离正确", close(d2, 0.5, 1e-6), f"{d2}")
    d3, _, _ = cast_ray(g, 1.5, 1.5, -1.0, 0.0)
    check("正西打墙距离正确", close(d3, 0.5, 1e-6), f"{d3}")

    # 垂直距离（不是欧氏距离），斜射不应出现鱼眼
    d4, _, _ = cast_ray(g, 1.5, 1.5, 1.0, 1.0)
    check("斜射返回垂直距离", close(d4, 0.5, 1e-6), f"{d4}")

    arena = build_arena()
    cam = Camera(*arena.center_free(), 0.0)
    dx, dy = cam.dir()
    d5, _, c5 = cast_ray(arena, cam.x, cam.y, dx, dy)
    check("靶场里射线能打到墙", 0.1 < d5 < 40.0, f"{d5:.2f}")


# ---------------------------------------------------------------- 命中

def open_spot(game, dist=9.0):
    """绕着相机找一个 `dist` 米外、视线通畅且不卡墙的落点。

    之前把靶子直接放在正东 9 米，结果那条线上正好有 x=21 的柱子，
    子弹被挡导致测试假阳性 —— 靶位必须由地图决定，不能硬编码。
    """
    import math as _m
    cam = game.cam
    for i in range(72):
        ang = i * (_m.tau / 72)
        x = cam.x + _m.cos(ang) * dist
        y = cam.y + _m.sin(ang) * dist
        if not (1.6 <= x <= game.gmap.w - 1.6 and 1.6 <= y <= game.gmap.h - 1.6):
            continue
        if game.gmap.blocked(x, y, 0.4):
            continue
        if not game.gmap.clear_line(cam.x, cam.y, x, y):
            continue
        if not game.gmap.clear_line(cam.x, cam.y,
                                    cam.x + _m.cos(ang) * (dist + 1.2),
                                    cam.y + _m.sin(ang) * (dist + 1.2)):
            continue     # 靶子后面还得留出余量，否则贴着墙不好判定
        return x, y
    raise AssertionError("地图里找不到通畅的测试落点")


def _aim_and_fire(game, target_world_pos, pitch_px=0.0, yaw_offset=0.0):
    """把相机对准某个世界坐标后开一枪，返回 (命中数增量, 分数增量)。"""
    cam = game.cam
    tx, ty = target_world_pos
    cam.yaw = math.atan2(ty - cam.y, tx - cam.x) + yaw_offset
    depth = math.hypot(tx - cam.x, ty - cam.y)
    # 让准星指向靶子胸口：h = 0.5 + pitch*d/(H*vscale)
    want_h = C.BOT_H * 0.55
    cam.pitch_px = (want_h - C.EYE_HEIGHT) * (game.renderer.h * game.renderer.vscale) / depth
    cam.pitch_px += pitch_px
    cam.apply_recoil(0.0, 0.0)
    game.player.apply_to_camera(cam, game.renderer)
    before_hits, before_score = game.hit_count, game.score
    game.fire()
    return game.hit_count - before_hits, game.score - before_score


def test_hitting():
    pygame.init()
    pygame.display.set_mode((1280, 720))
    from main import Game

    g = Game()
    g.range.set_mode("botz", g.cam)
    g.range.targets.clear()

    # 找一个视线通畅的落点，9 米外放靶
    tx, ty = open_spot(g, 9.0)
    depth = math.hypot(tx - g.cam.x, ty - g.cam.y)
    t = Target(tx, ty)
    g.range.targets.append(t)

    hits, score = _aim_and_fire(g, (tx, ty))
    check("正前方能打中躯干", hits == 1, f"hits={hits}")
    check("躯干得分正确", score == C.SCORE_BODY, f"{score}")
    check("一枪击杀", t not in g.range.targets)

    # 头部：把准星抬到头部区间正中
    g.range.targets.clear()
    t2 = Target(tx, ty)
    g.range.targets.append(t2)
    head_h = (C.HEAD_TOP + C.HEAD_BOT) * 0.5 * C.BOT_H
    g.cam.yaw = math.atan2(ty - g.cam.y, tx - g.cam.x)
    g.cam.pitch_px = (head_h - C.EYE_HEIGHT) * (g.renderer.h * g.renderer.vscale) / depth
    g.player.recoil_px = 0.0
    g.player.recoil_yaw_px = 0.0
    g.combo = 0          # 连击会跨测试累积，先归零再验基础分
    g.player.apply_to_camera(g.cam, g.renderer)
    s0 = g.score
    g.fire()
    check("打头得分更高", g.score - s0 == C.SCORE_HEAD, f"+{g.score - s0}")

    # 连击加成：连中第二发起才有（靶子加厚，避免一枪打死）
    g.range.targets.clear()
    t4 = Target(tx, ty)
    t4.hp = 10000.0
    g.range.targets.append(t4)
    g.cam.yaw = math.atan2(ty - g.cam.y, tx - g.cam.x)
    g.cam.pitch_px = (C.BOT_H * 0.55 - C.EYE_HEIGHT) * (
        g.renderer.h * g.renderer.vscale) / depth
    g.combo = 0
    g.score = 0
    g.player.cooldown = 0.0
    g.player.apply_to_camera(g.cam, g.renderer)
    g.fire()
    g.player.cooldown = 0.0
    g.fire()
    check("第二连击开始有加成",
          g.score == C.SCORE_BODY + int(C.SCORE_BODY * 1.05), f"{g.score} 分")

    # 背对目标 → 必定落空，且连击清零
    g.range.targets.clear()
    t3 = Target(g.cam.x - 9.0, g.cam.y)
    g.range.targets.append(t3)
    g.combo = 7
    g.player.cooldown = 0.0
    g.cam.yaw = 0.0
    g.cam.pitch_px = 0.0
    g.player.apply_to_camera(g.cam, g.renderer)
    h0 = g.hit_count
    g.fire()
    check("背对目标打不中", g.hit_count == h0)
    check("落空清零连击", g.combo == 0)

    # 墙后的目标打不到
    g.range.targets.clear()
    g.cam.x, g.cam.y = g.gmap.center_free()
    hidden = Target(g.cam.x, g.cam.y)
    # 找一面墙背后的位置
    hidden.x, hidden.y = 0.5, 0.5
    g.range.targets.append(hidden)
    g.cam.yaw = math.atan2(hidden.y - g.cam.y, hidden.x - g.cam.x)
    g.player.cooldown = 0.0
    g.player.apply_to_camera(g.cam, g.renderer)
    h1 = g.hit_count
    g.fire()
    check("墙内/墙后目标打不中", g.hit_count == h1)


# ---------------------------------------------------------------- 模式

def test_modes():
    g = build_arena()
    cam = Camera(*g.center_free())
    cam.apply_recoil(0.0, 0.0)
    for mode in MODE_KEYS:
        rng = Range(g, __import__("random").Random(7))
        rng.set_mode(mode, cam)
        check(f"{mode}: 开局就有靶子", len(rng.targets) > 0, f"{len(rng.targets)} 个")
        for _ in range(400):      # 跑 ~6 秒
            rng.update(1 / 60.0, cam)
        check(f"{mode}: 长跑不崩且仍有靶", len(rng.targets) > 0, f"{len(rng.targets)} 个")
        # 靶子不能刷在墙里
        inside = [t for t in rng.targets if g.blocked(t.x, t.y, 0.30)]
        check(f"{mode}: 靶子不在墙里", not inside, f"{len(inside)} 个越界")


# ---------------------------------------------------------------- 补位节奏

def test_respawn_delay():
    """清掉的靶不该立刻补位 —— 之前 pending 没占名额，延迟形同虚设。"""
    g = build_arena()
    cam = Camera()
    cam.apply_recoil(0.0, 0.0)
    rng = Range(g, __import__("random").Random(11))
    rng.set_mode("botz", cam)
    n0 = len(rng.targets)

    rng.remove(rng.targets[0])
    check("清掉一个靶", len(rng.targets) == n0 - 1, f"{len(rng.targets)}/{n0}")

    rng.update(1 / 120.0, cam)
    check("刷新延迟内不补位", len(rng.targets) == n0 - 1, f"{len(rng.targets)}")

    for _ in range(60):          # 等 1 秒，远大于 RESPAWN_DELAY
        rng.update(1 / 60.0, cam)
    check("延迟过后补回", len(rng.targets) == n0, f"{len(rng.targets)}/{n0}")


# ---------------------------------------------------------------- 焦点

def test_focus_loss():
    """切走窗口必须自动弹菜单、放开鼠标。

    否则鼠标被 grab 锁在窗口里、焦点又不在游戏上，用户就彻底动不了了。
    这条同时也锁住"别把事件名写错"——pygame 2 没有 WINDOWEVENT 这种
    带 .event 子属性的事件，写错会在运行时直接 AttributeError 崩掉。
    """
    from main import Game

    check("pygame 有 WINDOWFOCUSLOST 常量", hasattr(pygame, "WINDOWFOCUSLOST"))
    check("pygame 没有 WINDOWEVENT 常量（别写错）",
          not hasattr(pygame, "WINDOWEVENT"))

    g = Game()
    g.state = "play"
    g.player.firing = True
    pygame.event.clear()
    pygame.event.post(pygame.event.Event(pygame.WINDOWFOCUSLOST))
    g.handle_events()
    check("失焦后进入菜单", g.state == "menu")
    check("失焦后停止连发", not g.player.firing)

    # 最小化同理
    g.state = "play"
    pygame.event.clear()
    pygame.event.post(pygame.event.Event(pygame.WINDOWMINIMIZED))
    g.handle_events()
    check("最小化后进入菜单", g.state == "menu")


# ---------------------------------------------------------------- 视角轴向

def test_look_axis():
    """鼠标上下移动的方向必须和视角一致（修过一次反向 bug）。

    pygame 的 rel[1]：鼠标上移为负、下移为正。
    pitch_px 为正 = 视角上抬（aim_height 已验证）。
    所以正常（INVERT_Y=False）时：鼠标上移 → pitch_px 变大 → 视角上抬。
    """
    from main import Game
    import config as C

    g = Game()
    g.state = "play"

    # 鼠标上移（dy < 0）应让 pitch_px 增大（视角上抬）
    g.cam.pitch_px = 0.0
    g.look(0, -50)
    check("鼠标上移 → 视角上抬（pitch_px 增大）", g.cam.pitch_px > 0,
          f"pitch_px={g.cam.pitch_px:.1f}")

    # 鼠标下移（dy > 0）应让 pitch_px 减小（视角下压）
    g.cam.pitch_px = 0.0
    g.look(0, 50)
    check("鼠标下移 → 视角下压（pitch_px 减小）", g.cam.pitch_px < 0,
          f"pitch_px={g.cam.pitch_px:.1f}")

    # 开了 INVERT_Y 应该反过来
    C.INVERT_Y = True
    g.cam.pitch_px = 0.0
    g.look(0, -50)
    check("INVERT_Y 开启后：鼠标上移 → 视角下压", g.cam.pitch_px < 0,
          f"pitch_px={g.cam.pitch_px:.1f}")
    C.INVERT_Y = False

    # 左右不受 pitch 符号影响，方向应保持不变
    g.cam.yaw = 1.0
    g.look(10, 0)
    check("鼠标右移 → yaw 增大", g.cam.yaw > 1.0, f"yaw={g.cam.yaw:.3f}")


# ---------------------------------------------------------------- 狙击模式

def test_sniper():
    """SNIPER 模式 + 开镜 + 栓动，独立第 5 模式，不动其它模式。"""
    pygame.init()
    pygame.display.set_mode((1280, 720))
    from main import Game
    import config as C

    g = Game()
    g.set_mode("sniper")
    check("进入狙击模式", g.range.mode == "sniper")
    check("狙击开局就有远距靶", len(g.range.targets) > 0,
          f"{len(g.range.targets)} 个")
    # 远距靶应明显比普通靶远
    dmin = min(math.hypot(t.x - g.cam.x, t.y - g.cam.y) for t in g.range.targets)
    check("靶子确实够远", dmin >= C.SNIPER_DIST_MIN - 0.5, f"最近 {dmin:.1f}m")

    # —— 开镜：按住右键（play 态由事件置 ads），zoom 应平滑放大到 4x ——
    g.state = "play"
    g.player.ads = True
    for _ in range(120):
        g.update(1 / 60.0)
    check("开镜后 zoom 接近 4x", g.renderer.zoom > C.ADS_ZOOM * 0.9,
          f"zoom={g.renderer.zoom:.2f}")
    check("开镜时灵敏度被压低",
          g.sens * (C.SNIPER_SENS_MUL if g.player.ads else 1.0) < g.sens)

    # 松镜：zoom 应回到 1
    g.player.ads = False
    for _ in range(120):
        g.update(1 / 60.0)
    check("松镜后 zoom 回到 1", g.renderer.zoom < 1.1, f"zoom={g.renderer.zoom:.2f}")

    # —— 栓动：开火后上栓冷却内不能再开火 ——
    g.player.ads = True
    g.renderer.set_zoom(C.ADS_ZOOM)
    g.player.bolt = 0.0
    before = g.score
    g.fire_sniper()
    check("开火后进入上栓冷却", not g.player.can_bolt_fire(),
          f"bolt={g.player.bolt:.2f}")
    g.fire_sniper()                       # 上栓期间再点应无效
    check("上栓期间再点无效", g.score == before, f"score={g.score}")
    g.player.bolt = 0.0                   # 模拟上栓结束
    g.fire_sniper()
    check("上栓结束后可再次开火", g.player.bolt > 0.0)

    # —— 放大验证：同一点在 zoom=4 时投影更高 ——
    g.renderer.set_zoom(1.0)
    near = g.renderer.sprite_geom(g.cam, g.cam.x + 10, g.cam.y,
                                  C.SNIPER_BOT_H, C.SNIPER_BOT_W)
    g.renderer.set_zoom(C.ADS_ZOOM)
    far = g.renderer.sprite_geom(g.cam, g.cam.x + 10, g.cam.y,
                                 C.SNIPER_BOT_H, C.SNIPER_BOT_W)
    g.renderer.set_zoom(1.0)
    ok = bool(near and far and far[2] > near[2] * 1.5)
    check("开镜后靶子投影放大", ok, f"{near[2]:.0f} -> {far[2]:.0f}" if near and far else "n/a")


# ---------------------------------------------------------------- 冒烟

def test_smoke():
    from main import Game

    g = Game()
    g.range.set_mode("botz", g.cam)
    frames = 0
    for i in range(180):
        g.handle_events()
        g.update(1 / 60.0)
        g.draw()
        if i % 7 == 0:
            g.player.cooldown = 0.0
            g.cam.yaw += 0.31
            g.fire()
        frames += 1
    check("连续 180 帧不崩", frames == 180)

    # 画面确实画出了东西（不是纯黑 / 纯色）
    colors = set()
    for x in range(0, 1280, 37):
        for y in range(0, 720, 29):
            colors.add(g.screen.get_at((x, y))[:3])
    check("画面有层次（颜色数 > 8）", len(colors) > 8, f"{len(colors)} 种颜色")

    # 菜单能画出来
    g.state = "menu"
    g.draw()
    check("菜单能渲染", True)

    g.state = "play"
    for mode in MODE_KEYS:
        g.set_mode(mode)
        for _ in range(90):
            g.update(1 / 60.0)
            g.draw()
        check(f"模式 {mode} 渲染 90 帧正常", True)


def main():
    pygame.init()
    pygame.display.set_mode((1280, 720))   # 字体 / Renderer 都需要显示已初始化
    print("\n== GEOM AIM 自检 ==\n")
    test_map()
    print()
    test_font()
    print()
    test_projection()
    print()
    test_raycast()
    print()
    test_hitting()
    print()
    test_modes()
    print()
    test_respawn_delay()
    print()
    test_focus_loss()
    print()
    test_look_axis()
    print()
    test_sniper()
    print()
    test_smoke()
    print(f"\n通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
    if FAIL:
        for f in FAIL:
            print("  FAILED:", f)
        sys.exit(1)


if __name__ == "__main__":
    main()
