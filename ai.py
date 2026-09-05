"""3v3 对战的 AI：网格寻路 + 目标选择 + 交火。

两条硬约束：
1. **不碰 main._do_shot** —— AI 的开火判定在这里自己算一份（几何逻辑故意和玩家那份
   保持一致），这样 5 个练习模式一行不用动，不会为了加对战把练枪房改坏。
2. **AI 不作弊** —— 和玩家用同一套几何：瞄准点带高斯误差，误差超过目标的人形轮廓
   就算打偏；开火前必须过 clear_line 视线检查 + cast_ray 墙距检查。
   所以你移动、贴掩体、拉远是真能降低被命中率的，不存在"隔墙锁头"。

寻路为什么必须真做 BFS：地图是 12 个房间靠门洞连通的，墙很多，
"撞墙就转向"的笨办法会在门洞和墙角反复卡死，观感像智障。
"""

from __future__ import annotations

import math
import random
from collections import deque

import config as C
from engine import cast_ray, cast_ray_block, clamp, lerp


# ---------------------------------------------------------------- 网格 BFS

def bfs_path(gmap, start, goal, max_nodes: int = 12000):
    """格子级 BFS，返回路径格子列表（不含起点），不可达返回 None。

    gmap.at() == 0 才算可走 —— 掩体柱（type 2）同样挡路。
    地图约 109×58 = 6.3k 格，BFS 一次几毫秒，每个 AI 每 0.4s 重算一次足够。
    """
    sx, sy = int(start[0]), int(start[1])
    gx, gy = int(goal[0]), int(goal[1])
    if sx == gx and sy == gy:
        return []
    if gmap.at(gx, gy) != 0:
        return None

    prev = {(sx, sy): None}
    q = deque([(sx, sy)])
    nodes = 0
    while q:
        cx, cy = q.popleft()
        nodes += 1
        if nodes > max_nodes:
            break
        if cx == gx and cy == gy:
            path = []
            cur = (cx, cy)
            while prev[cur] is not None:
                path.append(cur)
                cur = prev[cur]
            path.reverse()
            return path
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = cx + dx, cy + dy
            if (nx, ny) in prev:
                continue
            if 0 <= nx < gmap.w and 0 <= ny < gmap.h and gmap.at(nx, ny) == 0:
                prev[(nx, ny)] = (cx, cy)
                q.append((nx, ny))
    return None


def _cell(p):
    return (int(p[0]), int(p[1]))


# ---------------------------------------------------------------- Agent

class Agent:
    """一个参战单位。玩家的"影子"也是一个 Agent（is_player=True），
    敌人的 AI 才能用同一套逻辑把它当目标打。"""

    def __init__(self, team: int, x: float, y: float, is_player: bool = False):
        self.team = team
        self.x = x
        self.y = y
        self.yaw = 0.0
        self.hp = C.AGENT_HP
        self.alive = True
        self.is_player = is_player

        # 渲染用（复用 hud.draw_target，字段名和 Target 对齐）
        self.h = C.BOT_H
        self.w = C.BOT_W
        self.flash = 0.0
        self.kind = "agent"

        # AI 状态
        self.state = "idle"        # idle / advance / engage / search
        self.target = None
        self.react = 0.0           # 反应延迟剩余
        self.fire_cd = 0.0
        self.burst_left = 0
        self.path: list = []
        self.path_timer = 0.0
        self.goal_cell = None
        self.strafe_sign = 1
        self.strafe_timer = 0.0
        self.last_seen = None
        self.lost_timer = 0.0
        self.roam = None           # 无目标时的游走点
        self.muzzle = 0.0          # 枪口火光计时
        self.stuck = 0             # 连续卡墙计数（用于兜底绕行）

        # 武器库存（对战回合制）：每回合开始重置回手枪，同一回合内买过的枪
        # 随时用 C 键来回切。loadout 存武器 key（见 weapons.MATCH_WEAPONS），
        # w_idx 指向当前那把。
        self.loadout: list[str] = ["pistol"]
        self.w_idx = 0

        # 弹药（仅 3v3 对战生效）：mags[武器key] = 弹匣里的余弹。
        # 不在 dict 里的枪视为满弹（积分赛/练习不做弹药限制）。
        # reload_t > 0 = 正在换弹，期间不能开火；切枪打断换弹（余弹保留）。
        self.mags: dict = {}
        self.reload_t = 0.0

        # 战术：偷背身。flank_goal 非空 = 正在绕后；flank_cd 是两次包抄的冷却。
        self.flank_goal = None     # (x, y) 打算绕到的落点
        self.flank_t = 0.0         # 本次包抄已用时（超时就放弃）
        self.flank_cd = 0.0        # 距下次可以起意包抄还剩多久

        # 投掷物：AI 自己的烟雾弹携带量与冷却（玩家那套在 Game 上，这里只管 AI）
        self.smoke_charges = 0     # 本回合手里还有几颗
        self.smoke_cd = 0.0        # 投掷冷却（秒）
        # 出手意图：场景判定通过先不扔，记下方向并起一个随机延迟，
        # 延迟走完再按概率决定出不出手——避免所有人同一帧一起扔。
        self.smoke_intent = 0.0    # >0 表示有 pending 的投掷意图，值即剩余延迟
        self.smoke_aim = None      # (dx, dy) 打算扔的方向

        # 重生 / 无敌 / 蹲（积分赛用；回合赛里 invuln 恒为 0、crouch 影响命中轮廓）
        self.respawn_timer = 0.0
        self.invuln = 0.0
        self.crouch = False

        # 地形：脚下地面高度（高度图采样）。每帧在 update_agent 里刷新。
        self.ground_z = 0.0

        # 联机：控制来源。"ai"=本地 AI 驱动；"local"=主机真人；"human"=联网真人。
        # 只有 "ai" 才走 update_agent，其余由各自的输入驱动。
        self.controller = "ai"
        self.z = 0.0             # 离地高度（跳跃），投影用
        self.vz = 0.0            # 垂直速度
        self.remote_id = None     # 联网时分配的客户端编号
        self.uid = 0             # 场内唯一编号（联机快照用它定位每个客户端自己的 Agent）
        self.name = "BOT"
        # 个人战绩（整场累积，随快照同步给客户端，用于结算面板）
        self.kills = 0
        self.deaths = 0
        self.shots = 0
        self.hits = 0

    @property
    def dead(self) -> bool:
        return not self.alive


# ---------------------------------------------------------------- 感知

def _visible(m, a, e) -> bool:
    if not e.alive:
        return False
    d = math.hypot(e.x - a.x, e.y - a.y)
    if d > C.AI_VIEW_RANGE or d < 1e-3:
        return False
    # 高度感知视线：蹲在矮箱后（头顶 < 箱高）的目标看不见，站着露头才看得见。
    # 地形：眼睛与目标都按"脚下地面高度"抬到绝对高度，山脊会挡、洼地能藏。
    eye_z = a.h * 0.5
    if not m.gmap.clear_line_h(a.x, a.y, eye_z, e.x, e.y, e.h,
                               g0=a.ground_z, g1=e.ground_z):
        return False
    # 烟是双向封视线的：隔着烟看不见，自己站烟里也看不见外面
    return not m.smokes.blocks(a.x, a.y, e.x, e.y)


def pick_target(m, a):
    """最近的可见敌人。看不见就返回 None（不隔墙感知）。"""
    best, best_d = None, 1e9
    for e in m.agents:
        if e.team == a.team or not e.alive:
            continue
        d = math.hypot(e.x - a.x, e.y - a.y)
        if d < best_d and _visible(m, a, e):
            best, best_d = e, d
    return best


def turn_toward(cur: float, want: float, max_step: float) -> float:
    diff = (want - cur + math.pi) % (2 * math.pi) - math.pi
    if abs(diff) <= max_step:
        return want
    return cur + math.copysign(max_step, diff)


# ---------------------------------------------------------------- 移动

def _move(m, a, dx: float, dy: float, step: float) -> bool:
    d = math.hypot(dx, dy)
    if d < 1e-6:
        return False
    ux, uy = dx / d, dy / d
    nx, ny = a.x + ux * step, a.y + uy * step
    if not m.gmap.blocked(nx, ny, 0.30):
        a.x, a.y = nx, ny
        return True
    # 直走被墙挡：尝试只走 X 或只走 Y，沿墙滑行，避免在墙角原地卡死
    if not m.gmap.blocked(a.x + ux * step, a.y, 0.30):
        a.x += ux * step
        return True
    if not m.gmap.blocked(a.x, a.y + uy * step, 0.30):
        a.y += uy * step
        return True
    return False


def _follow_path(m, a, dt: float, speed: float):
    """沿 BFS 路径走。每帧做"一步拉直"：能直达下下个点就丢掉当前点，
    否则 AI 会贴着格子中心走出锯齿状轨迹。

    卡墙兜底：直走被挡时先尝试沿墙滑行（见 _move）；若某个节点近在咫尺又
    走不过去（多半是贴着柱子/墙角），直接跳过它改走下一个；连续多帧完全
    卡死则清空路径强制重算，避免在墙边原地踏步。
    """
    if not a.path:
        return
    gmap = m.gmap
    while len(a.path) > 1:
        nx, ny = a.path[1]
        # 半径感知：只有身体（半径 0.30）真能沿直线穿过去才剪枝，否则保留
        # 门洞/柱子附近的节点，避免 AI 被「中轴线穿过但身体过不去」的捷径拖死。
        if gmap.clear_corridor(a.x, a.y, nx + 0.5, ny + 0.5, 0.30):
            a.path.pop(0)
        else:
            break

    cx, cy = a.path[0]
    tx, ty = cx + 0.5, cy + 0.5
    d = math.hypot(tx - a.x, ty - a.y)
    if d < 0.40:
        a.path.pop(0)
        a.stuck = 0
        return
    if _move(m, a, tx - a.x, ty - a.y, speed * dt):
        a.stuck = 0
        return
    # 近但走不过去：多半是卡在柱子/墙角，跳过该节点改走下一个
    if d < 0.9:
        a.path.pop(0)
        a.stuck = 0
        return
    # 连续卡墙：清空路径，下一帧 _repath 会因 path_timer<=0 重算
    a.stuck += 1
    if a.stuck >= 4:
        a.stuck = 0
        a.path = []
        a.path_timer = 0.0
        a.goal_cell = None


def _repath(m, a, gx: float, gy: float, rng: random.Random):
    cell = _cell((gx, gy))
    if a.goal_cell == cell and a.path and a.path_timer > 0:
        return
    p = bfs_path(m.gmap, (a.x, a.y), (gx, gy))
    if p is None:
        # 目标点不可达（比如落在柱子里）：退而求其次找个附近的开放点
        spot = m.gmap.random_free(rng, pad=1.8)
        if spot:
            p = bfs_path(m.gmap, (a.x, a.y), (spot[0], spot[1]))
    a.path = p or []
    a.goal_cell = cell
    a.path_timer = C.AI_PATH_REPLAN


# ---------------------------------------------------------------- 投掷物

def _ai_do_throw(m, a, dx: float, dy: float):
    """真正扔一颗烟。返回是否扔成功（场上满了会失败）。"""
    if m.smokes.throw(a.x, a.y, C.EYE_HEIGHT, dx, dy, team=a.team) is None:
        return False
    a.smoke_charges -= 1
    a.smoke_cd = C.SMOKE_AI_COOLDOWN
    return True


def _team_clouds(m, team: int) -> int:
    """该队目前还在场上（含飞行中、未消散）的烟团数量。"""
    return sum(1 for g in m.smokes.grenades
               if not g.done and g.team == team)


def _smoke_plan(m, a, rng, dt: float):
    """按场景判断要不要扔、往哪扔。返回 (dx, dy) 方向，None 表示这一帧不打算扔。

    * 中远距离封锁长视线：烟落在自己与目标之间，切断这条枪线（封路烟）。
    * 低血撤退：血量见底且已脱离交火时，封住最后看见敌人的方向。
    * 掩护推进：无目标时低频朝前进方向扔，概率按 dt 计（不按帧）。
    近距离（小于 SMOKE_AI_MIN_DIST）一律不扔——那个距离扔烟等于糊自己的脸。
    """
    tgt = a.target

    if tgt is not None and _visible(m, a, tgt):
        d = math.hypot(tgt.x - a.x, tgt.y - a.y)
        if C.SMOKE_AI_MIN_DIST <= d <= C.SMOKE_AI_MAX_DIST:
            # 这条线已经被烟挡住了就别再浪费一颗
            if not m.smokes.blocks(a.x, a.y, tgt.x, tgt.y):
                return (tgt.x - a.x, tgt.y - a.y)
        return None                       # 太近、太远、或已被烟封住

    if a.hp <= C.SMOKE_AI_HP_RETREAT and a.last_seen is not None:
        lx, ly = a.last_seen
        if not m.smokes.blocks(a.x, a.y, lx, ly):
            return (lx - a.x, ly - a.y)

    if tgt is None and a.path and rng.random() < C.SMOKE_AI_ADV_RATE * dt:
        cx, cy = a.path[0]
        return ((cx + 0.5) - a.x, (cy + 0.5) - a.y)

    return None


def ai_maybe_throw_smoke(m, a, rng: random.Random, dt: float = 0.0):
    """AI 用烟：过闸 → 判场景 → 随机延迟 → 概率出手。

    之前是「看见 7~32 格的敌人就立刻扔」，开局全员齐扔把地图铺满。
    现在每一步都有闸，且出手时间被打散，不会再出现同时铺三团的情况。
    """
    # 1) 硬闸：弹药、冷却、开局冷静期、本队配额、自己已在烟里
    if a.smoke_charges <= 0 or a.smoke_cd > 0:
        return
    if m.live_t < C.SMOKE_AI_CALM:
        return
    if _team_clouds(m, a.team) >= C.SMOKE_AI_TEAM_MAX:
        return
    if m.smokes.hides(a.x, a.y):
        return

    # 2) 有 pending 的投掷意图：等延迟走完再按概率决定
    if a.smoke_intent > 0.0:
        a.smoke_intent -= dt
        if a.smoke_intent > 0.0:
            return
        a.smoke_intent = 0.0
        aim, a.smoke_aim = a.smoke_aim, None
        if aim is not None and rng.random() < C.SMOKE_AI_CHANCE:
            _ai_do_throw(m, a, aim[0], aim[1])
        return

    # 3) 场景判定：得出一个想扔的方向
    aim = _smoke_plan(m, a, rng, dt)
    if aim is None:
        return

    # 4) 起随机延迟，把大家的出手时间错开
    a.smoke_aim = aim
    a.smoke_intent = rng.uniform(C.SMOKE_AI_DELAY_MIN, C.SMOKE_AI_DELAY_MAX)


# ---------------------------------------------------------------- 战术：偷背身

def back_exposed(tgt, from_x: float, from_y: float) -> bool:
    """目标是不是把背露给了 (from_x, from_y) 这个位置。

    判据是「目标朝向」与「目标 → 观察者」这两个向量的夹角余弦：
    接近 +1 表示目标正对着你（正面刚枪），接近 -1 表示背对着你（可以偷）。
    """
    dx, dy = from_x - tgt.x, from_y - tgt.y
    d = math.hypot(dx, dy)
    if d < 1e-6:
        return False
    dot = (math.cos(tgt.yaw) * dx + math.sin(tgt.yaw) * dy) / d
    return dot < C.AI_FLANK_BACK_DOT


def flank_point(gmap, tgt, rng: random.Random, radius: float | None = None):
    """在目标"身后"找一个能站的包抄落点；身后全是墙就返回 None（放弃包抄）。

    落点 = 目标位置 + 目标朝向的反方向 × radius，左右各试几个偏角，
    挑第一个既不在墙里、身体又站得下的点。
    """
    radius = C.AI_FLANK_RADIUS if radius is None else radius
    back = tgt.yaw + math.pi
    side = 1 if rng.random() < 0.5 else -1
    for offset in (0.0, side * 0.6, -side * 0.6, side * 1.1, -side * 1.1):
        ang = back + offset
        x = tgt.x + math.cos(ang) * radius
        y = tgt.y + math.sin(ang) * radius
        if gmap.blocked(x, y, 0.35):
            continue
        return (x, y)
    return None


def _flank_rate(tune: dict, exposed: bool) -> float:
    """每秒起意包抄的"速率"（配合 dt 用）。难度越高越爱绕，目标背身时更想绕。"""
    skill = clamp(tune.get("burst", 0.5), 0.0, 1.0)
    rate = lerp(C.AI_FLANK_CHANCE_MIN, C.AI_FLANK_CHANCE_MAX, skill)
    if exposed:
        rate *= C.AI_FLANK_BACK_BONUS
    return min(rate, 3.0)


# ---------------------------------------------------------------- 弹药

def ammo_of(a) -> int:
    """当前武器的余弹。没记录过的枪视为满弹（积分赛/练习不做弹药限制）。"""
    return a.mags.get(a.weapon.key, a.weapon.mag)


def start_reload(a) -> bool:
    """开始换弹：已满或正在换就不动。返回是否真的开始了。"""
    if a.reload_t > 0:
        return False
    if ammo_of(a) >= a.weapon.mag:
        return False
    a.reload_t = C.RELOAD_TIME
    return True


def cancel_reload(a):
    """切枪打断换弹：余弹保留在弹匣里，换弹进度清零。"""
    a.reload_t = 0.0


def tick_reload(a, dt: float) -> bool:
    """换弹计时；走完补满弹匣。返回"这一帧刚完成换弹"。"""
    if a.reload_t <= 0:
        return False
    a.reload_t -= dt
    if a.reload_t <= 0:
        a.reload_t = 0.0
        a.mags[a.weapon.key] = a.weapon.mag
        return True
    return False


# ---------------------------------------------------------------- 开火

def _try_fire(m, a, dt: float, rng: random.Random, tune: dict):
    a.fire_cd -= dt
    if a.fire_cd > 0:
        return
    tgt = a.target
    if tgt is None or not tgt.alive:
        return

    # 弹药（仅 3v3 对战）：换弹中打不了；打空自动换弹
    if m.mode == "match":
        if a.reload_t > 0:
            return
        if ammo_of(a) <= 0:
            start_reload(a)
            return

    dist = math.hypot(tgt.x - a.x, tgt.y - a.y)
    eye_z = a.ground_z + a.h * 0.5
    chest = tgt.ground_z + tgt.h * 0.62         # 瞄胸口，和命中判定一致
    slope = (chest - eye_z) / max(dist, 1e-3)
    if not m.gmap.clear_line_h(a.x, a.y, eye_z, tgt.x, tgt.y, tgt.h,
                               g0=a.ground_z, g1=tgt.ground_z):
        return
    # 烟挡视线：目标躲进烟里（或自己站在烟里）就别开枪了
    if m.smokes.blocks(a.x, a.y, tgt.x, tgt.y):
        return

    # 扣一发子弹（打进墙里也算打出去的一发）
    if m.mode == "match":
        a.mags[a.weapon.key] = ammo_of(a) - 1

    dxr, dyr = math.cos(a.yaw), math.sin(a.yaw)
    wall_d = cast_ray_block(m.gmap, a.x, a.y, dxr, dyr, eye_z, slope)
    if dist >= wall_d:
        a.muzzle = 0.12           # 打在墙上了（矮箱也会挡住打向胸口的弹道）
        a.fire_cd = 0.20
        return

    # —— 命中判定（几何与玩家那份一致）——
    sigma = math.radians(tune["sigma"])
    lat = rng.gauss(0.0, sigma)          # 水平角误差（弧度）
    vert = rng.gauss(0.0, sigma)         # 垂直角误差（弧度）
    pux, puy = -math.sin(a.yaw), math.cos(a.yaw)
    rx, ry = tgt.x - a.x, tgt.y - a.y
    depth = rx * dxr + ry * dyr
    lateral = rx * pux + ry * puy
    lat_eff = lateral + lat * depth

    a.muzzle = 0.12
    hit = abs(lat_eff) <= tgt.w * 0.5
    head = False
    if hit:
        h_aim = tgt.h * 0.62 + vert * depth     # 瞄胸口 + 垂直误差
        hit = 0.0 <= h_aim <= tgt.h
        if hit:
            scale = tgt.w / C.BOT_W
            head = (C.HEAD_BOT * tgt.h <= h_aim <= C.HEAD_TOP * tgt.h
                    and abs(lat_eff) <= C.HEAD_HALF_W * scale)

    if hit:
        m.apply_damage(a, tgt, head)
    else:
        m.on_shot_missed(a)

    # —— 点射节奏：burst 越高，连发越长、停歇越短 ——
    skill = clamp(tune["burst"], 0.0, 1.0)
    if a.burst_left <= 0:
        a.burst_left = int(lerp(2, 7, skill))
        a.fire_cd = lerp(0.55, 0.22, skill)
    else:
        a.burst_left -= 1
        a.fire_cd = a.weapon.fire_interval if hasattr(a, "weapon") else 0.10


# ---------------------------------------------------------------- 主更新

def update_agent(m, a, dt: float, rng: random.Random, tune: dict):
    if not a.alive or a.controller != "ai":
        return
    if m.state != "live":
        return                       # 买枪/结算阶段 AI 不动手

    if a.muzzle > 0:
        a.muzzle = max(0.0, a.muzzle - dt)
    if a.flash > 0:
        a.flash = max(0.0, a.flash - dt * 3.0)

    a.path_timer -= dt
    a.strafe_timer -= dt
    if a.smoke_cd > 0:
        a.smoke_cd = max(0.0, a.smoke_cd - dt)

    # 换弹计时（3v3）：走完补满弹匣；没在换弹时是空操作
    tick_reload(a, dt)

    # 脚下地形高度（高度图采样）；平整地图 h_at 恒返回 0，无副作用。
    a.ground_z = m.gmap.h_at(a.x, a.y)

    # 1) 目标选择
    tgt = pick_target(m, a)
    if tgt is not a.target:
        a.target = tgt
        a.react = tune["reaction"]      # 新目标/刚发现 -> 重新起反应延迟
    if tgt is not None:
        a.last_seen = (tgt.x, tgt.y)
        a.lost_timer = 0.0

    # 1.5) 有烟就考虑用（封长视线 / 撤退掩护 / 低频推进掩护）
    ai_maybe_throw_smoke(m, a, rng, dt)

    if tgt is not None:
        a.state = "engage"
        dist = math.hypot(tgt.x - a.x, tgt.y - a.y)
        # 中远距离蹲下：缩小命中轮廓（"蹲点"），近距保持机动不蹲
        a.crouch = dist > 9.0
        a.h = C.BOT_H * C.CROUCH_H_MUL if a.crouch else C.BOT_H
        want = math.atan2(tgt.y - a.y, tgt.x - a.x)
        # 转头速度也受难度影响：越难转得越快
        a.yaw = turn_toward(a.yaw, want, lerp(3.0, 9.0, tune["burst"]) * dt)

        a.react -= dt
        if a.react <= 0:
            _try_fire(m, a, dt, rng, tune)

        # —— 战术：偷背身（背身偷袭 / 绕后包抄）——
        a.flank_cd = max(0.0, a.flank_cd - dt)
        exposed = back_exposed(tgt, a.x, a.y)

        # 1) 已经在包抄路上：到了、超时、血少了、贴脸了就收手回正面对枪
        if a.flank_goal is not None:
            a.flank_t += dt
            reached = math.hypot(a.flank_goal[0] - a.x, a.flank_goal[1] - a.y) < 1.0
            if (a.flank_t > C.AI_FLANK_MAX_T or a.hp <= C.AI_FLANK_HP_MIN
                    or dist < C.AI_FLANK_MIN_DIST or reached):
                a.flank_goal = None
                a.flank_t = 0.0
                a.flank_cd = C.AI_FLANK_CD
        # 2) 否则按速率掷骰决定要不要绕后
        elif (C.AI_FLANK_ENABLED and a.flank_cd <= 0.0
              and C.AI_FLANK_MIN_DIST < dist < C.AI_FLANK_MAX_DIST
              and a.hp > C.AI_FLANK_HP_MIN
              and rng.random() < _flank_rate(tune, exposed) * dt):
            pt = flank_point(m.gmap, tgt, rng)
            if pt is not None:
                a.flank_goal = pt
                a.flank_t = 0.0
                a.path = []
                a.goal_cell = None

        speed = C.AI_MOVE_SPEED * tune["move_mul"]
        if a.flank_goal is not None:
            # 绕后中：沿路径走向包抄点，但身体保持朝目标（路上照样能开枪）
            _repath(m, a, a.flank_goal[0], a.flank_goal[1], rng)
            _follow_path(m, a, dt, speed)
        elif exposed and dist > C.AI_FLANK_MIN_DIST:
            # 目标把背露给我：悄悄压上去偷，别原地横移把自己送进枪口
            _repath(m, a, tgt.x, tgt.y, rng)
            _follow_path(m, a, dt, speed * C.AI_FLANK_PUSH_MUL)
        elif dist > 13.0:
            _repath(m, a, tgt.x, tgt.y, rng)
            _follow_path(m, a, dt, speed)
        else:
            if a.strafe_timer <= 0:
                a.strafe_timer = C.AI_STRAFE_PERIOD * rng.uniform(0.6, 1.4)
                a.strafe_sign = rng.choice((-1, 1))
            px, py = -math.sin(a.yaw), math.cos(a.yaw)   # 视线法线
            step = speed * dt * (0.35 + 0.65 * tune["strafe"])
            moved = _move(m, a, px * a.strafe_sign, py * a.strafe_sign, step)
            if moved:
                a.stuck = 0
            else:
                a.strafe_sign = -a.strafe_sign
                a.stuck += 1
                # 横移被墙夹死（墙角两侧都挡）：改为朝目标寻路绕行，
                # 而不是在原地反复横跳——这就是"卡墙边不动"的根因。
                if a.stuck >= 2:
                    a.stuck = 0
                    _repath(m, a, tgt.x, tgt.y, rng)
                    _follow_path(m, a, dt, speed)
    else:
        a.state = "search"
        a.crouch = False
        a.h = C.BOT_H
        a.flank_goal = None          # 目标没了就不绕了
        a.flank_t = 0.0
        a.lost_timer += dt
        goal = None
        if a.last_seen and a.lost_timer < C.AI_LOSE_TARGET:
            goal = a.last_seen                       # 追最后看到的位置
        else:
            if a.roam is None or math.hypot(a.roam[0] - a.x, a.roam[1] - a.y) < 1.5:
                spot = m.gmap.random_free(rng, pad=2.0)
                a.roam = spot if spot else (a.x, a.y)
            goal = a.roam
        _repath(m, a, goal[0], goal[1], rng)
        _follow_path(m, a, dt, C.AI_MOVE_SPEED * tune["move_mul"])
        # 面朝前进方向
        if a.path:
            cx, cy = a.path[0]
            a.yaw = turn_toward(a.yaw, math.atan2(cy + 0.5 - a.y, cx + 0.5 - a.x),
                                4.0 * dt)
