"""HUD：准星、计分、靶子绘制、枪模型、暂停菜单。"""

from __future__ import annotations

import math

import pygame

import config as C
from engine import clamp, lerp_rgb
from targets import MODE_KEYS, MODE_NAMES

CJK_FONT_PATHS = (
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/STHeiti Light.ttc",
    "/System/Library/Fonts/PingFang.ttc",
)

_font_cache: dict[int, pygame.font.Font] = {}
_font_path: str | None = None      # 实际生效的字体文件；None = 退到 pygame 兜底字体


def font(size: int) -> pygame.font.Font:
    global _font_path
    f = _font_cache.get(size)
    if f is not None:
        return f
    f = None
    for path in CJK_FONT_PATHS:
        try:
            f = pygame.font.Font(path, size)
            _font_path = path
            break
        except Exception:
            continue
    if f is None:
        # pygame 自带位图字体没有中文字形，只能显示英文 —— 需要报警
        f = pygame.font.Font(None, size)
        _font_path = None
    _font_cache[size] = f
    return f


def text(surf, s, size, pos, color=C.C_TEXT, anchor="tl", alpha=None):
    img = font(size).render(s, True, color)
    if alpha is not None and alpha < 255:
        img.set_alpha(int(alpha))
    r = img.get_rect()
    x, y = pos
    if "r" in anchor:
        x -= r.width
    elif "c" in anchor:
        x -= r.width * 0.5
    if "b" in anchor:
        y -= r.height
    elif "m" in anchor:
        y -= r.height * 0.5
    surf.blit(img, (int(x), int(y)))
    return r


# ---------------------------------------------------------------- 靶子

def draw_target(surf, renderer, cam, t, body=None, head=None, edge=None):
    """画一个几何小人，返回 (中心 x, 脚底 y, 高, 宽, 深度) 供特效用。

    body/head/edge 是可选的队伍配色 —— 不传就是原来靶子的蓝/橙，
    所以 5 个练习模式的观感一个像素都不会变，只有对战传队伍色进来。
    """
    geom = renderer.sprite_geom(cam, t.x, t.y, t.h, t.w,
                                 getattr(t, "ground_z", 0.0))
    if geom is None:
        return None
    cx, yb, hpx, wpx, depth = geom
    if hpx < 4 or wpx < 2:
        return None
    x0, x1 = cx - wpx * 0.5, cx + wpx * 0.5
    if x1 < -40 or x0 > renderer.w + 40:
        return None
    runs = renderer.visible_runs(x0, x1, depth)
    if not runs:
        return None

    base_body = body if body is not None else C.C_BOT
    base_head = head if head is not None else C.C_BOT_HEAD
    flash = t.flash
    body = lerp_rgb(base_body, C.C_BOT_HIT, flash) if flash else base_body
    head = lerp_rgb(base_head, C.C_BOT_HIT, flash) if flash else base_head
    edge = edge if edge is not None else C.C_BOT_EDGE

    hw = wpx * (C.HEAD_HALF_W * 2.0 / C.BOT_W)
    head_top = yb - C.HEAD_TOP * hpx
    head_h = max(2.0, (C.HEAD_TOP - C.HEAD_BOT) * hpx)

    leg_top = yb - hpx * 0.46
    leg_w = max(1.0, wpx * 0.17)
    torso_top = yb - hpx * 0.80
    torso_bot = yb - hpx * 0.34
    torso_w = wpx * 0.74

    parts = [
        # (rect, 填充色, 描边)
        ((cx - wpx * 0.26, leg_top, leg_w, yb - leg_top), body),
        ((cx + wpx * 0.26 - leg_w, leg_top, leg_w, yb - leg_top), body),
        ((cx - torso_w * 0.5, torso_top, torso_w, torso_bot - torso_top), body),
        ((cx - hw * 0.5, head_top, hw, head_h), head),
    ]

    old_clip = surf.get_clip()
    for ra, rb, top_y in runs:
        # top_y = 这一段里最近的半高箱顶边。精灵只画它以上的部分 ——
        # 蹲在矮箱后就是这样被"切掉"下半身、甚至整个藏住的。
        clip_h = renderer.h if top_y is None else int(top_y)
        if clip_h <= 0:
            continue                      # 整段都被箱子挡死
        clip_h = min(clip_h, renderer.h)
        surf.set_clip(pygame.Rect(int(ra), 0, max(1, int(rb - ra)), clip_h))
        # 脚下投影
        pygame.draw.ellipse(surf, C.C_SHADOW,
                            (cx - wpx * 0.32, yb - hpx * 0.02,
                             wpx * 0.64, max(2.0, hpx * 0.045)))
        for rect, col in parts:
            rx, ry, rw, rh = rect
            pygame.draw.rect(surf, edge, (rx - 2, ry - 2, rw + 4, rh + 4))
            pygame.draw.rect(surf, col, (rx, ry, rw, rh))
        # 胸口一道亮条，几何感
        pygame.draw.rect(surf, lerp_rgb(body, (255, 255, 255), 0.55),
                         (cx - torso_w * 0.28, torso_top + hpx * 0.06,
                          torso_w * 0.56, max(1.0, hpx * 0.035)))
    surf.set_clip(old_clip)
    return cx, yb, hpx, wpx, depth


# ---------------------------------------------------------------- 枪模型

def muzzle_pos(renderer, player):
    """枪口在屏幕上的位置（开火特效和绘制共用同一套算法）。"""
    u = renderer.h / 720.0
    w, h = renderer.w, renderer.h
    bob_x = math.sin(player.bob) * 7.0 * u
    bob_y = abs(math.cos(player.bob)) * 5.0 * u
    kick = player.kick
    ox = w * 0.72 + bob_x + kick * 10.0 * u
    oy = h * 1.02 + bob_y + kick * 26.0 * u
    return (ox - 18 * u, oy - 79 * u)


def draw_ammo(surf, renderer, ammo: int, mag: int, reload_t: float):
    """右下角武器上方的弹药读数（仅 3v3 对战调用）。

    换弹时显示"换弹中…"+ 进度条；弹匣打空数字变警示色。
    """
    u = renderer.h / 720.0
    x = int(renderer.w * 0.72)
    y = int(renderer.h * 0.78)
    if reload_t > 0.0:
        text(surf, "换弹中…", 17, (x, y), C.C_ACCENT, anchor="rm")
        k = clamp(1.0 - reload_t / C.RELOAD_TIME, 0.0, 1.0)
        bw, bh = int(120 * u), max(3, int(5 * u))
        bx = x - bw // 2
        pygame.draw.rect(surf, (60, 66, 82), (bx, y + 14, bw, bh))
        pygame.draw.rect(surf, C.C_ACCENT, (bx, y + 14, int(bw * k), bh))
        return
    col = C.C_TEXT if ammo > 0 else C.C_WARN
    text(surf, f"{ammo} / {mag}", 20, (x, y), col, anchor="rm")


def draw_weapon(surf, renderer, player):
    """右下角的几何枪，返回枪口屏幕坐标。"""
    u = renderer.h / 720.0
    w, h = renderer.w, renderer.h
    bob_x = math.sin(player.bob) * 7.0 * u
    bob_y = abs(math.cos(player.bob)) * 5.0 * u
    kick = player.kick
    ox = w * 0.72 + bob_x + kick * 10.0 * u
    oy = h * 1.02 + bob_y + kick * 26.0 * u

    def P(pts, col):
        pygame.draw.polygon(surf, col,
                            [(ox + px * u, oy + py * u) for px, py in pts])

    P([(250, -30), (110, -58), (-18, -98), (-18, -60), (110, -20), (250, 6)],
      (58, 66, 84))                                        # 机匣 + 枪管
    P([(250, -12), (218, 74), (162, 74), (188, -12)], (44, 50, 66))   # 握把
    P([(178, -6), (152, 62), (104, 56), (136, -8)], (38, 44, 58))     # 弹匣
    P([(120, -56), (10, -92), (10, -84), (120, -48)], (86, 96, 118))  # 上沿高光
    P([(196, -26), (196, -18), (240, -6), (240, -16)], C.C_ACCENT)    # 霓虹条

    muzzle = muzzle_pos(renderer, player)

    if player.kick > 0.05:
        k = player.kick
        import random as _r
        cx, cy = muzzle
        for i in range(3):
            ang = -math.pi * 0.75 + i * 0.5 + _r.uniform(-0.15, 0.15)
            ln = (34 + i * 16) * u * k
            pygame.draw.polygon(surf, (255, 226 - i * 30, 140 - i * 40), [
                (cx, cy),
                (cx + math.cos(ang - 0.28) * ln, cy + math.sin(ang - 0.28) * ln),
                (cx + math.cos(ang) * ln * 1.5, cy + math.sin(ang) * ln * 1.5),
                (cx + math.cos(ang + 0.28) * ln, cy + math.sin(ang + 0.28) * ln),
            ])
        pygame.draw.circle(surf, (255, 246, 214), (int(cx), int(cy)), int(9 * u * k))

    return muzzle


# ---------------------------------------------------------------- 准星

def draw_crosshair(surf, renderer, player, style: int):
    cx, cy = renderer.w * 0.5, renderer.h * 0.5
    gap = clamp(3.0 + player.spread * 2300.0, 3.0, 64.0)
    if player.moving:
        gap += 4.0
    length = 8.0
    thick = 2
    col = C.C_MARK
    if style == 0:      # 粗十字
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            pygame.draw.line(
                surf, col,
                (cx + dx * gap, cy + dy * gap),
                (cx + dx * (gap + length), cy + dy * (gap + length)), thick)
    elif style == 1:    # 点
        pygame.draw.circle(surf, col, (int(cx), int(cy)), 2)
    else:               # 空心十字（带中心点）
        pygame.draw.circle(surf, col, (int(cx), int(cy)), 1)
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            pygame.draw.line(
                surf, col,
                (cx + dx * gap, cy + dy * gap),
                (cx + dx * (gap + length * 0.7), cy + dy * (gap + length * 0.7)), 1)


# ---------------------------------------------------------------- 狙击镜

def draw_scope(surf, renderer, player):
    """开镜时画圆形镜框：镜外全黑、镜内透出画面，带十字线与 mil-dot。

    实现：用 mask 把圆内挖成透明，再 blit 一张「圆外黑、圆内透明」的遮罩，
    把世界盖住、只留镜内可见。不影响其它模式（只在 SNIPER + 开镜时调用）。
    """
    w, h = renderer.w, renderer.h
    cx, cy = w // 2, h // 2
    rad = int(min(w, h) * 0.43)

    # 圆外黑、圆内透明的遮罩
    circ = pygame.Surface((w, h), pygame.SRCALPHA)
    pygame.draw.circle(circ, (255, 255, 255, 255), (cx, cy), rad)
    cmask = pygame.mask.from_surface(circ)
    veil = pygame.mask.Mask((w, h), fill=True)   # 默认全黑
    # 注意：这个版本的 pygame 里 Mask.erase 的 offset 参数是必填的，必须显式传 (0,0)，
    # 否则会抛 "missing required argument 'offset'"，在开镜那一帧直接把进程带崩（看起来像游戏自动退出）。
    veil.erase(cmask, (0, 0))                     # 圆内 -> 透明
    black = veil.to_surface(setcolor=(0, 0, 0, 255), unsetcolor=(0, 0, 0, 0))
    surf.blit(black, (0, 0))

    # 镜圈
    pygame.draw.circle(surf, C.C_SCOPE_RING, (cx, cy), rad, 3)
    pygame.draw.circle(surf, C.C_SCOPE_RING, (cx, cy), rad - 3, 1)

    # 十字线
    pygame.draw.line(surf, C.C_SCOPE_LINE, (cx - rad, cy), (cx + rad, cy), 1)
    pygame.draw.line(surf, C.C_SCOPE_LINE, (cx, cy - rad), (cx, cy + rad), 1)
    # mil-dot：沿十字线向两侧排布的小点
    for i in range(1, 6):
        off = rad * i / 7.0
        for (dx, dy) in ((off, 0), (-off, 0), (0, off), (0, -off)):
            pygame.draw.circle(surf, C.C_SCOPE_LINE, (int(cx + dx), int(cy + dy)), 1)

    # 镜内细微偏绿（夜视味，可选）
    tint = pygame.Surface((rad * 2, rad * 2), pygame.SRCALPHA)
    tint.fill(C.C_SCOPE_TINT + (18,))
    surf.blit(tint, (cx - rad, cy - rad),
              special_flags=pygame.BLEND_RGBA_ADD)

    # 上栓冷却提示（在中下方）
    if player.bolt > 0.02:
        frac = clamp(player.bolt / max(0.001, C.BOLT_TIME), 0.0, 1.0)
        bw = rad * 1.1
        bx, by = cx - bw * 0.5, cy + rad * 0.62
        pygame.draw.rect(surf, (40, 52, 78), (bx, by, bw, 5))
        pygame.draw.rect(surf, C.C_WARN, (bx, by, bw * frac, 5))


# ---------------------------------------------------------------- 计分板

def draw_scoreboard(surf, renderer, game):
    w = renderer.w
    text(surf, game.mode_name(), 26, (26, 20), C.C_ACCENT)
    text(surf, game.mode_hint(), 15, (26, 52), C.C_DIM)

    mult = game.combo_multiplier()
    text(surf, f"{game.score:,}", 40, (w - 26, 18), C.C_TEXT, anchor="tr")
    if game.combo > 1:
        col = C.C_BOT_HEAD if game.combo >= 10 else C.C_TEXT
        text(surf, f"x{mult:.2f}   {game.combo} COMBO", 17, (w - 26, 64), col, anchor="tr")
    else:
        text(surf, f"{game.hit_count} HITS", 15, (w - 26, 66), C.C_DIM, anchor="tr")

    # 连击剩余时间条
    if game.combo > 1 and game.combo_timer > 0:
        frac = clamp(game.combo_timer / C.COMBO_TIMEOUT, 0.0, 1.0)
        bar_w = 150.0
        x = w - 26 - bar_w
        y = 88
        pygame.draw.rect(surf, (40, 52, 78), (x, y, bar_w, 4))
        pygame.draw.rect(surf, C.C_ACCENT, (x, y, bar_w * frac, 4))

    if game.hint_alpha > 0:
        a = int(255 * clamp(game.hint_alpha, 0.0, 1.0))
        text(surf, "WASD 移动   鼠标 转视角   左键 开火   空格 跳   G 烟雾弹   C 切枪   R 换弹   ESC 菜单",
             15, (w * 0.5, renderer.h - 34), C.C_DIM, anchor="cm", alpha=a)


# ---------------------------------------------------------------- 投掷物 / 跳跃提示

def draw_smoke_slot(surf, renderer, game):
    """左下角：烟雾弹余量、冷却条，以及滞空时的"打不准"提示。"""
    h = renderer.h
    x, y = 26.0, h - 78.0
    n = game.smoke_left
    cd = game.smoke_cd

    if n <= 0:
        text(surf, "G  烟雾弹  已用完", 16, (x, y), C.C_DIM)
    else:
        text(surf, f"G  烟雾弹  x{n}", 16, (x, y), C.C_TEXT)

    if cd > 0.0:
        frac = clamp(cd / C.SMOKE_COOLDOWN, 0.0, 1.0)
        pygame.draw.rect(surf, (40, 52, 78), (x, y + 24, 96, 4))
        pygame.draw.rect(surf, C.C_ACCENT, (x, y + 24, 96 * (1.0 - frac), 4))

    if game.player.airborne:
        text(surf, "滞空中 · 精度下降", 15, (x, y - 26), C.C_WARN)


# ---------------------------------------------------------------- 对战 HUD

def _bar(surf, x, y, w, h, frac, col, bg=(40, 52, 78)):
    pygame.draw.rect(surf, bg, (x, y, w, h))
    if frac > 0:
        pygame.draw.rect(surf, col, (x, y, w * max(0.0, min(1.0, frac)), h))


def draw_match_hud(surf, renderer, game):
    """对战 HUD：比分 / 回合 / 计时 / 存活人数 / 血条 / 金钱 / 买枪菜单 / 击杀提示。"""
    m = game.match
    w, h = renderer.w, renderer.h

    # —— 顶部中间：比分 + 回合 + 计时 ——
    text(surf, f"{m.score[0]}  :  {m.score[1]}", 34, (w * 0.5, 14),
         C.C_TEXT, anchor="cm")
    label = f"第 {m.round_no} 回合 / 先到 {C.MATCH_WINS_NEEDED} 胜"
    text(surf, label, 14, (w * 0.5, 46), C.C_DIM, anchor="cm")

    secs = max(0.0, m.timer)
    clock_col = C.C_WARN if (m.state == "live" and secs <= 10.0) else C.C_ACCENT
    text(surf, f"{secs:05.1f}", 26, (w * 0.5, 58), clock_col, anchor="cm")

    phase = {"prep": "买枪阶段", "live": "交火中",
             "round_end": "回合结束", "match_end": "比赛结束"}[m.state]
    text(surf, phase, 15, (w * 0.5, 88), C.C_DIM, anchor="cm")

    # —— 左上：存活人数 ——
    a0, a1 = m._alive(0), m._alive(1)
    text(surf, f"我方 {a0}", 18, (26, 20), C.C_ALLY_HUD)
    text(surf, f"敌方 {a1}", 18, (26, 44), C.C_ENEMY_HUD)

    # —— 左下：血量 + 金钱 + 当前武器 ——
    hp = max(0, m.player_hp)
    text(surf, f"{hp}", 30, (26, h - 78),
         C.C_GOOD if hp > 50 else (C.C_WARN if hp > 25 else C.C_ENEMY))
    _bar(surf, 26, h - 46, 190, 8, hp / float(C.PLAYER_HP),
         C.C_GOOD if hp > 50 else C.C_WARN)
    text(surf, f"$ {m.player_money}", 20, (26, h - 30), C.C_ACCENT)
    wname = game.player.weapon.name
    text(surf, wname, 16, (w - 26, h - 30), C.C_DIM, anchor="br")

    # —— 买枪菜单 ——
    if m.state == "prep":
        _draw_buy_menu(surf, renderer, m)

    # —— 回合结算条幅 ——
    if m.state == "round_end":
        msg = {"win": "回合胜利", "lose": "回合失败", "draw": "平局"}.get(m.round_result, "")
        col = {"win": C.C_ALLY_HUD, "lose": C.C_ENEMY_HUD, "draw": C.C_DIM}[m.round_result]
        text(surf, msg, 46, (w * 0.5, h * 0.34), col, anchor="cm")

    # —— 阵亡观战提示 ——
    if m.player_dead:
        veil = pygame.Surface((w, h), pygame.SRCALPHA)
        veil.fill((90, 8, 20, 70))
        surf.blit(veil, (0, 0))
        text(surf, "你已阵亡 · 观战中", 30, (w * 0.5, h * 0.62), C.C_ENEMY_HUD, anchor="cm")
        text(surf, "等本回合结束自动复活", 15, (w * 0.5, h * 0.66), C.C_DIM, anchor="cm")

    # —— 比赛结束 ——
    if m.state == "match_end":
        _draw_match_end(surf, renderer, game)

    # —— 击杀提示（右下）——
    y = h * 0.42
    for txt, col, ttl in m.feed:
        a = int(255 * max(0.0, min(1.0, ttl / 1.2)))
        text(surf, txt, 16, (w - 26, y), col, anchor="tr", alpha=a)
        y += 24


def _draw_buy_menu(surf, renderer, m):
    from weapons import BUY_ORDER, MATCH_WEAPONS
    w, h = renderer.w, renderer.h
    rows = len(BUY_ORDER) + 1          # +1 = 烟雾弹
    pw, ph = 430, 62 + rows * 30
    px, py = (w - pw) * 0.5, h - ph - 60
    pygame.draw.rect(surf, C.C_PANEL, (px, py, pw, ph))
    pygame.draw.rect(surf, C.C_ACCENT, (px, py, pw, ph), 2)
    text(surf, "买枪（1-5）  ·  6 烟雾弹", 18, (px + 18, py + 12), C.C_ACCENT)
    text(surf, f"$ {m.player_money}", 18, (px + pw - 18, py + 12), C.C_TEXT, anchor="tr")

    # 库存：买过的枪一直留着，所以菜单要标出来哪些能直接切
    owned = list(getattr(m.player_agent, "loadout", []) or [])
    cur_idx = int(getattr(m.player_agent, "w_idx", 0) or 0)
    y = py + 44
    for i, key in enumerate(BUY_ORDER):
        wp = MATCH_WEAPONS[key]
        have = key in owned
        equipped = have and owned.index(key) == cur_idx
        afford = have or m.player_money >= wp.price
        col = C.C_TEXT if afford else C.C_DIM
        tag = " · 装备中" if equipped else (" · 已拥有" if have else "")
        text(surf, f"  {i + 1}. {wp.name}{tag}", 17, (px + 18, y),
             C.C_ACCENT if equipped else col)
        text(surf, "切换" if have else f"$ {wp.price}", 17, (px + pw - 18, y),
             col, anchor="tr")
        y += 30

    afford = m.player_money >= C.SMOKE_PRICE
    col = C.C_TEXT if afford else C.C_DIM
    text(surf, f"  6. 烟雾弹", 17, (px + 18, y), col)
    text(surf, f"$ {C.SMOKE_PRICE}", 17, (px + pw - 18, y), col, anchor="tr")


def _draw_match_end(surf, renderer, game):
    m = game.match
    w, h = renderer.w, renderer.h
    veil = pygame.Surface((w, h), pygame.SRCALPHA)
    veil.fill((6, 9, 15, 215))
    surf.blit(veil, (0, 0))

    won = m.player_won
    title = "胜利" if won else "失败"
    col = C.C_ALLY_HUD if won else C.C_ENEMY_HUD
    text(surf, title, 58, (w * 0.5, h * 0.28), col, anchor="cm")
    text(surf, f"{m.score[0]} : {m.score[1]}", 30, (w * 0.5, h * 0.37),
         C.C_TEXT, anchor="cm")

    st = m.stats
    acc = (100.0 * st["hits"] / st["shots"]) if st["shots"] else 0.0
    lines = [
        f"击杀 {st['kills']}      阵亡 {st['deaths']}",
        f"命中率 {acc:.1f}%      爆头 {st['headshots']}",
        f"难度 {game.difficulty}   自适应偏移 {m.adapt * C.AI_ADAPT_BAND * 100:+.0f}%",
    ]
    y = h * 0.48
    for ln in lines:
        text(surf, ln, 20, (w * 0.5, y), C.C_TEXT, anchor="cm")
        y += 32
    text(surf, "R 再来一局      ESC 菜单", 18, (w * 0.5, h * 0.72), C.C_ACCENT, anchor="cm")


# ---------------------------------------------------------------- 积分赛 HUD

def draw_score_hud(surf, renderer, game):
    """积分赛 HUD：双方击杀数（先到 25 杀）/ 存活人数 / 血条 / 自由换枪提示 /
    重生无敌 / 阵亡倒计时 / 击杀提示 / 结算面板。"""
    m = game.match
    w, h = renderer.w, renderer.h
    target = float(C.SCORE_KILL_TARGET)

    # —— 顶部中间：双方击杀数 ——
    k0, k1 = m.team_kills[0], m.team_kills[1]
    text(surf, f"{k0}  :  {k1}", 36, (w * 0.5, 12), C.C_TEXT, anchor="cm")
    text(surf, f"积分赛 5v5 · 先到 {C.SCORE_KILL_TARGET} 杀获胜", 14,
         (w * 0.5, 46), C.C_DIM, anchor="cm")

    # 双方进度条
    bar_w = 220.0
    bx, by = w * 0.5 - bar_w * 0.5, 64
    pygame.draw.rect(surf, (40, 52, 78), (bx, by, bar_w, 5))
    pygame.draw.rect(surf, C.C_ALLY_HUD,
                     (bx, by, bar_w * clamp(k0 / target, 0.0, 1.0), 5))
    pygame.draw.rect(surf, (40, 52, 78), (bx, by + 7, bar_w, 5))
    pygame.draw.rect(surf, C.C_ENEMY_HUD,
                     (bx, by + 7, bar_w * clamp(k1 / target, 0.0, 1.0), 5))

    # —— 左上：存活人数 ——
    a0, a1 = m._alive(0), m._alive(1)
    text(surf, f"我方 {a0}", 18, (26, 20), C.C_ALLY_HUD)
    text(surf, f"敌方 {a1}", 18, (26, 44), C.C_ENEMY_HUD)

    # —— 左下：血量 + 换枪提示；右下：当前武器 ——
    hp = max(0, m.player_hp)
    text(surf, f"{hp}", 30, (26, h - 78),
         C.C_GOOD if hp > 50 else (C.C_WARN if hp > 25 else C.C_ENEMY))
    _bar(surf, 26, h - 46, 190, 8, hp / float(C.PLAYER_HP),
         C.C_GOOD if hp > 50 else C.C_WARN)
    text(surf, "1-5 自由换枪（无经济）", 15, (26, h - 30), C.C_ACCENT)
    text(surf, game.player.weapon.name, 16, (w - 26, h - 30), C.C_DIM, anchor="br")

    # —— 重生无敌倒计时 ——
    inv = m.player_agent.invuln
    if inv > 0 and not m.player_dead:
        text(surf, f"重生无敌 {inv:.1f}s", 15, (w * 0.5, h * 0.80),
             C.C_ACCENT, anchor="cm")

    # —— 阵亡：观战 + 重生倒计时 ——
    if m.player_dead:
        veil = pygame.Surface((w, h), pygame.SRCALPHA)
        veil.fill((90, 8, 20, 70))
        surf.blit(veil, (0, 0))
        text(surf, "你已阵亡 · 观战中", 30, (w * 0.5, h * 0.60),
             C.C_ENEMY_HUD, anchor="cm")
        text(surf, f"{max(0.0, m.player_respawn):.1f}s 后重生（带 "
                   f"{C.SCORE_INVULN:.0f}s 无敌）", 16, (w * 0.5, h * 0.645),
             C.C_DIM, anchor="cm")

    # —— 比赛结束 ——
    if m.state == "match_end":
        _draw_score_end(surf, renderer, game)

    # —— 击杀提示（右下）——
    y = h * 0.42
    for txt, col, ttl in m.feed:
        a = int(255 * max(0.0, min(1.0, ttl / 1.2)))
        text(surf, txt, 16, (w - 26, y), col, anchor="tr", alpha=a)
        y += 24


def _draw_score_end(surf, renderer, game):
    m = game.match
    w, h = renderer.w, renderer.h
    veil = pygame.Surface((w, h), pygame.SRCALPHA)
    veil.fill((6, 9, 15, 215))
    surf.blit(veil, (0, 0))

    won = m.player_won
    title = "胜利" if won else "失败"
    col = C.C_ALLY_HUD if won else C.C_ENEMY_HUD
    text(surf, title, 58, (w * 0.5, h * 0.28), col, anchor="cm")
    text(surf, f"{m.team_kills[0]} : {m.team_kills[1]}", 30, (w * 0.5, h * 0.37),
         C.C_TEXT, anchor="cm")

    # 联机客户端：match.stats 是主机的战绩，这里必须用自己 agent 的数据
    me = None
    if getattr(game, "net_mode", "none") == "client":
        uid = getattr(game, "client_uid", None)
        for a in m.agents:
            if getattr(a, "uid", None) == uid:
                me = a
                break

    if me is not None:
        acc = (100.0 * me.hits / me.shots) if me.shots else 0.0
        lines = [
            f"击杀 {me.kills}      阵亡 {me.deaths}",
            f"命中率 {acc:.1f}%",
            f"先到 {C.SCORE_KILL_TARGET} 杀",
        ]
    else:
        st = m.stats
        acc = (100.0 * st["hits"] / st["shots"]) if st["shots"] else 0.0
        lines = [
            f"击杀 {st['kills']}      阵亡 {st['deaths']}",
            f"命中率 {acc:.1f}%      爆头 {st['headshots']}",
            f"难度 {game.difficulty}   先到 {C.SCORE_KILL_TARGET} 杀",
        ]
    y = h * 0.48
    for ln in lines:
        text(surf, ln, 20, (w * 0.5, y), C.C_TEXT, anchor="cm")
        y += 32
    # 联机主机不能 R 重开（会重建比赛导致房间错乱），提示改为收房
    if getattr(game, "net_mode", "none") == "host":
        text(surf, "H 返回标题（收房）", 18, (w * 0.5, h * 0.72),
             C.C_ACCENT, anchor="cm")
    else:
        text(surf, "R 再来一局      ESC 菜单", 18, (w * 0.5, h * 0.72),
             C.C_ACCENT, anchor="cm")


# ---------------------------------------------------------------- 标题界面

def draw_title(surf, renderer, game):
    w, h = renderer.w, renderer.h
    veil = pygame.Surface((w, h), pygame.SRCALPHA)
    veil.fill((6, 9, 15, 190))
    surf.blit(veil, (0, 0))

    text(surf, "GEOM AIM", 58, (w * 0.5, h * 0.16), C.C_ACCENT, anchor="cm")
    text(surf, "伪 3D 练枪房 / 3v3 回合制对战 / 5v5 积分赛", 17, (w * 0.5, h * 0.24),
         C.C_DIM, anchor="cm")

    text(surf, "1    练习模式（靶场 5 种）", 22, (w * 0.5, h * 0.36), C.C_TEXT, anchor="cm")
    text(surf, "2    对战模式  3v3  ·  best of 7 先到 4 胜", 22, (w * 0.5, h * 0.43),
         C.C_ACCENT, anchor="cm")
    text(surf, "3    积分赛  5v5  ·  先到 25 杀  ·  连续重生", 22, (w * 0.5, h * 0.50),
         C.C_ACCENT, anchor="cm")
    text(surf, "4    创建局域网房间（人类 vs AI，最多 3 人）", 22, (w * 0.5, h * 0.57),
         C.C_TEXT, anchor="cm")
    text(surf, "5    加入局域网房间（输入主机 IP 或 .local）", 22, (w * 0.5, h * 0.64),
         C.C_TEXT, anchor="cm")

    diff = game.difficulty
    text(surf, f"[  ]    AI 难度： {DIFF_LABEL.get(diff, diff)}", 18,
         (w * 0.5, h * 0.72), C.C_TEXT, anchor="cm")
    text(surf, "WASD 移动 · 鼠标 转视角 · 左键 开火 · 右键 开镜 · 空格 跳 · E 蹲 · G 烟雾弹 · ESC 菜单",
         13, (w * 0.5, h * 0.82), C.C_DIM, anchor="cm")
    text(surf, "H 返回主菜单 · Q 退出", 15, (w * 0.5, h * 0.86), C.C_DIM, anchor="cm")


DIFF_LABEL = {"easy": "简单", "normal": "普通", "hard": "困难", "expert": "专家"}


# ---------------------------------------------------------------- 菜单

MENU_LINES = [
    "1 - 5           切换模式（5 = SNIPER 狙击）",
    "[  ]            鼠标灵敏度 - / +",
    "-  =            视场角 FOV - / +",
    "C               切换准星样式",
    "M               静音开关",
    "L               热重载配色（改完 config.py 按它）",
    "R               重置当前模式",
    "H               返回主菜单",
    "Q               退出",
    "ESC             继续游戏",
]


def draw_menu(surf, renderer, game):
    w, h = renderer.w, renderer.h
    veil = pygame.Surface((w, h), pygame.SRCALPHA)
    veil.fill((6, 9, 15, 205))
    surf.blit(veil, (0, 0))

    pw, ph = 560, 660
    px, py = (w - pw) * 0.5, (h - ph) * 0.5
    pygame.draw.rect(surf, C.C_PANEL, (px, py, pw, ph))
    pygame.draw.rect(surf, C.C_ACCENT, (px, py, pw, ph), 2)

    text(surf, "GEOM AIM", 40, (px + 32, py + 26), C.C_ACCENT)
    text(surf, "练枪房 / aim trainer", 15, (px + 34, py + 74), C.C_DIM)

    y = py + 112
    text(surf, "模式", 15, (px + 32, y), C.C_DIM)
    y += 24
    for i, key in enumerate(MODE_KEYS):
        on = (game.range.mode == key)
        col = C.C_ACCENT if on else C.C_TEXT
        label = f"  {i + 1}. {MODE_NAMES[key]}"
        text(surf, label, 20, (px + 30, y), col)
        if on:
            pygame.draw.circle(surf, C.C_ACCENT, (int(px + 40), int(y + 12)), 3)
        y += 30

    y += 12
    text(surf, f"鼠标灵敏度   {game.sens * 1000:.2f}", 18, (px + 32, y), C.C_TEXT)
    y += 28
    text(surf, f"视场角 FOV   {game.hfov:.0f}°", 18, (px + 32, y), C.C_TEXT)
    y += 28
    text(surf, f"准星         {('十字', '圆点', '细十字')[game.crosshair]}",
         18, (px + 32, y), C.C_TEXT)
    y += 28
    text(surf, f"音效         {'关' if game.audio.muted else '开'}",
         18, (px + 32, y), C.C_TEXT)

    y += 40
    for line in MENU_LINES:
        text(surf, line, 15, (px + 32, y), C.C_DIM)
        y += 21
