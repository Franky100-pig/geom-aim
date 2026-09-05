"""3v3 对战：回合状态机、队伍、经济、胜负。

赛制：best of 7 先到 4 胜。每回合 = 买枪(10s) → 交火(90s) → 结算(2.6s)。
回合内一条命，死了观战到回合结束；时间到按存活人数判，人数相同算平局、双方不得分。

经济：只卖枪（无护甲）和烟雾弹（每颗 $150），照 CS 的量级：起始 800 / 胜 3250 /
败 1400 起、连败补偿递增到 3400 / 上限 16000。玩家、队友 AI、敌人 AI 都能买烟，
队友和敌人最多各带 2 颗并在交火中真扔；飞行中直接命中敌人会造成 SMOKE_DIRECT_DMG
伤害（落地变烟后不再造成伤害，且不对同队生效）。

难度：四档预设 + 逐回合自适应（只在基准 ±20% 内浮动，不会突然变得离谱）。
"""

from __future__ import annotations

import math
import random

import config as C
from ai import Agent, update_agent
from engine import clamp, cast_ray_block
from nades import SmokeField
from weapons import BUY_ORDER, MATCH_WEAPONS, match_weapon

FEED_TTL = 4.0


def _safe_spawn(gmap, p, rng=None):
    """出生点若正好落在柱子里，由内向外找一个能站人的格子。"""
    cx, cy = int(p[0]), int(p[1])
    if not gmap.blocked(cx + 0.5, cy + 0.5, 0.5):
        return (cx + 0.5, cy + 0.5)
    for rad in range(1, 12):
        for dx in range(-rad, rad + 1):
            for dy in range(-rad, rad + 1):
                if max(abs(dx), abs(dy)) != rad:
                    continue
                x, y = cx + dx, cy + dy
                if 1 <= x < gmap.w - 1 and 1 <= y < gmap.h - 1:
                    if not gmap.blocked(x + 0.5, y + 0.5, 0.5):
                        return (x + 0.5, y + 0.5)
    return (cx + 0.5, cy + 0.5)


def team_spawns(gmap):
    """两队出生点：拼接地图的两个对角房间中心。

    尺寸从 gmap 本身携带的 room_w/room_h/tiles_x/tiles_y 取，不再读全局
    ARENA_* —— 这样对战用小地图（2×2）也能算对，练习大地图也不受影响。
    """
    sx = gmap.room_w + 1
    sy = gmap.room_h + 1

    def room_center(ix, iy):
        return (ix * sx + 1 + gmap.room_w // 2,
                iy * sy + 1 + gmap.room_h // 2)

    a = room_center(0, 0)
    b = room_center(gmap.tiles_x - 1, gmap.tiles_y - 1)
    return [_safe_spawn(gmap, a), _safe_spawn(gmap, b)]


class Match:
    def __init__(self, gmap, rng: random.Random | None = None,
                 difficulty: str = C.AI_DIFF_DEFAULT, smokes=None, mode: str = "match"):
        self.gmap = gmap
        self.rng = rng or random.Random()
        self.difficulty = difficulty if difficulty in C.AI_PRESETS else C.AI_DIFF_DEFAULT
        self.mode = mode              # "match" = 回合制 3v3；"score" = 5v5 连续重生 TDM
        # 烟场：Game 会把练习/对战共用的那一个传进来，省得两套状态对不上
        self.smokes = smokes if smokes is not None else SmokeField()

        self.spawns = team_spawns(gmap)
        self.agents: list[Agent] = []
        self.player_agent: Agent | None = None

        self.score = [0, 0]
        self.round_no = 0
        self.state = "prep"          # prep / live / round_end / match_end（score 模式恒 live）
        self.timer = C.MATCH_BUY_TIME
        self.live_t = 0.0            # 本回合「交火阶段」已进行的秒数（AI 用烟的开局冷静期依据）
        self.round_result = None     # win / lose / draw

        self.player_money = C.ECON_START
        self.player_hp = C.PLAYER_HP   # 玩家血量只在这里存一份，HUD 和 AI 都读它
        self.player_dead = False
        self.spectate: Agent | None = None

        # 联机：真人（含主机）的输入都塞进这个字典，由 _drive_humans 每帧驱动。
        # key = Agent 对象，value = 输入字典（见 net.py / Game 的 _pack_input）。
        self.human_inputs: dict = {}
        self.human_count = 1          # 已占用的真人 slot 数（含主机，开局就是 1）
        self._uid_seq = 0             # Agent.uid 自增计数器（联机快照用它定位每个客户端自己的 Agent）

        # 积分赛（TDM）状态
        self.team_size = C.SCORE_TEAM_SIZE if mode == "score" else 3
        self.team_kills = [0, 0]
        self.player_respawn = 0.0

        self.loss_streak = [0, 0]
        self.feed: list = []         # [文本, 颜色, 剩余时间]
        self.stats = dict(kills=0, deaths=0, shots=0, hits=0, headshots=0)

        # 自适应状态
        self.adapt = 0.0             # -1(放水) .. +1(加压)
        self.perf = 0.0
        self._last_k = 0
        self._last_d = 0

        self._build_agents()
        self.player_agent.controller = "local"   # 主机真人（区别于 AI / 联网真人）
        self._apply_tune()
        if mode == "score":
            self._start_score()
        else:
            self.start_round()

    # ------------------------------------------------------------ 构建

    def _build_agents(self):
        # 玩家影子：位置/血量由 Game 同步，AI 逻辑不会去驱动它
        p = Agent(0, self.spawns[0][0], self.spawns[0][1], is_player=True)
        p.weapon = match_weapon("pistol")
        p.uid = self._next_uid()
        self.player_agent = p
        self.agents.append(p)

        for team in (0, 1):
            base = self.spawns[team]
            # 队 0 已有玩家影子，所以再补 (team_size-1) 个 AI 队友；队 1 直接 team_size 个敌人
            n = (self.team_size - 1) if team == 0 else self.team_size
            for i in range(n):
                ang = math.tau * (i + 1) / (n + 1)
                x = base[0] + math.cos(ang) * 2.2
                y = base[1] + math.sin(ang) * 2.2
                if self.gmap.blocked(x, y, 0.4):
                    x, y = base
                a = Agent(team, x, y)
                a.weapon = match_weapon("pistol")
                a.money = C.ECON_START
                a.uid = self._next_uid()
                self.agents.append(a)

    def _place_all(self):
        """把两队摆回出生点，并朝向敌方出生点。"""
        for team in (0, 1):
            base = self.spawns[team]
            foe = self.spawns[1 - team]
            want = math.atan2(foe[1] - base[1], foe[0] - base[0])
            mates = [a for a in self.agents if a.team == team and not a.is_player]
            n = len(mates)
            for i, a in enumerate(mates):
                ang = math.tau * (i + 1) / (n + 1)
                x = base[0] + math.cos(ang) * 2.2
                y = base[1] + math.sin(ang) * 2.2
                if self.gmap.blocked(x, y, 0.4):
                    x, y = base
                a.x, a.y = x, y
                a.yaw = want
                a.path = []
                a.goal_cell = None
                a.roam = None

    # ------------------------------------------------------------ 联机真人

    def _next_uid(self) -> int:
        """分配一个场内唯一的 Agent 编号（联机快照用它定位每个客户端自己的 Agent）。"""
        u = self._uid_seq
        self._uid_seq += 1
        return u

    def add_human_agent(self, team: int, name: str) -> "Agent":
        """加入一个联网真人。优先顶替本队一个 AI 保持 5v5 平衡；
        本队没有 AI 可顶替时才追加（理论上不会发生：队 0 常驻 4 个 AI）。"""
        # 队伍平衡：顶掉本队一个 AI。alive=False 先标死，防止其他 AI 的
        # target 还指着这个被移除的对象追空气。
        for i, x in enumerate(self.agents):
            if x.team == team and x.controller == "ai":
                x.alive = False
                del self.agents[i]
                break
        base = self.spawns[team]
        ox = self.rng.uniform(-2.0, 2.0)
        oy = self.rng.uniform(-2.0, 2.0)
        x, y = base[0] + ox, base[1] + oy
        if self.gmap.blocked(x, y, 0.4):
            x, y = base
        a = Agent(team, x, y)
        a.weapon = match_weapon("rifle")
        a.controller = "human"
        a.is_player = False
        a.name = name
        a.uid = self._next_uid()
        self.agents.append(a)
        self.human_count += 1
        return a

    def remove_human_agent(self, a: "Agent"):
        """踢掉一个联网真人（超时/断线时）。"""
        if a in self.agents:
            self.agents.remove(a)
        self.human_inputs.pop(a, None)
        self.human_count = max(1, self.human_count - 1)

    def _drive_humans(self, dt: float):
        """把 human_inputs 里的输入应用到对应真人 Agent 上（主机每帧调用）。"""
        for a in self.agents:
            if a.controller != "human":
                continue
            inp = self.human_inputs.get(a)
            if inp is None:
                continue
            self._apply_human(a, inp, dt)

    def _apply_human(self, a: "Agent", inp: dict, dt: float):
        if not a.alive:
            return
        speed = C.HUMAN_MOVE_SPEED
        fx, fy = math.cos(a.yaw), math.sin(a.yaw)        # 前
        rx, ry = -math.sin(a.yaw), math.cos(a.yaw)       # 右
        mvx = float(inp.get("mvx", 0.0))
        mvy = float(inp.get("mvy", 0.0))
        nx = a.x + (fx * mvx + rx * mvy) * speed * dt
        ny = a.y + (fy * mvx + ry * mvy) * speed * dt
        # 碰撞：用 0.35 半径近似人，撞墙就不动（不穿墙）
        if not self.gmap.blocked(nx, ny, 0.35) and not self.gmap.blocked(nx, a.y, 0.35):
            a.x = nx
        if not self.gmap.blocked(a.x, ny, 0.35) and not self.gmap.blocked(nx, ny, 0.35):
            a.y = ny

        dyaw = float(inp.get("dyaw", 0.0))
        a.yaw = (a.yaw + dyaw) % math.tau

        a.crouch = bool(inp.get("crouch", False))
        a.h = C.BOT_H * C.CROUCH_H_MUL if a.crouch else C.BOT_H

        # 跳跃（简单重力积分）
        if bool(inp.get("jump", False)) and a.z <= 0.0 and a.vz <= 0.0:
            a.vz = C.HUMAN_JUMP_V
        a.vz -= C.HUMAN_GRAVITY * dt
        a.z += a.vz * dt
        if a.z <= 0.0:
            a.z = 0.0
            a.vz = 0.0

        w = inp.get("weapon")
        if w and str(w) in MATCH_WEAPONS:
            key = str(w)
            # 库存里已有 → 直接切；没有 → 只在买枪阶段才允许买（交火中不能凭空变枪）
            if not self._select(a, key) and self.state == "prep":
                self._buy(a, key)

        if bool(inp.get("fire", False)) and a.fire_cd <= 0.0:
            self.fire_human(a)

        if bool(inp.get("smoke", False)) and a.smoke_charges > 0:
            eye = a.h * 0.5 + a.z
            dx, dy = math.cos(a.yaw), math.sin(a.yaw)
            if self.smokes.throw(a.x, a.y, eye, dx, dy, team=a.team) is not None:
                a.smoke_charges -= 1

        if a.fire_cd > 0:
            a.fire_cd = max(0.0, a.fire_cd - dt)
        if a.muzzle > 0:
            a.muzzle = max(0.0, a.muzzle - dt)

    def fire_human(self, a: "Agent"):
        """真人开火：从 Agent 当前位置/朝向做命中判定（几何与玩家 _do_shot 一致）。"""
        a.shots += 1
        eye_z = a.ground_z + a.h * 0.5 + a.z
        dx, dy = math.cos(a.yaw), math.sin(a.yaw)
        pux, puy = -math.sin(a.yaw), math.cos(a.yaw)
        # 打对面队伍
        pool = ([x for x in self.agents if x.team != a.team and x.alive]
                if a.team == 0 else [x for x in self.agents if x.team == 0 and x.alive])
        best, best_d, headshot = None, 1e9, False
        for t in pool:
            rx, ry = t.x - a.x, t.y - a.y
            depth = rx * dx + ry * dy
            if depth <= 0.35 or depth >= best_d:
                continue
            lateral = rx * pux + ry * puy
            if abs(lateral) > t.w * 0.5:
                continue
            h_aim = t.ground_z + t.h * 0.62
            if h_aim < 0.0 or h_aim > t.ground_z + t.h:
                continue
            slope = (h_aim - eye_z) / depth
            wall_d = cast_ray_block(self.gmap, a.x, a.y, dx, dy, eye_z, slope)
            if depth >= wall_d:
                continue
            if not self.gmap.clear_line_h(a.x, a.y, eye_z, t.x, t.y, t.h,
                                         g0=0.0, g1=t.ground_z):
                continue
            if self.smokes.blocks(a.x, a.y, t.x, t.y):
                continue
            scale = t.w / C.BOT_W
            head = (C.HEAD_BOT * t.h <= h_aim <= C.HEAD_TOP * t.h
                    and abs(lateral) <= C.HEAD_HALF_W * scale)
            best, best_d, headshot = t, depth, head
        if best is not None:
            a.hits += 1
            self.apply_damage(a, best, headshot)
        a.muzzle = 0.12
        a.fire_cd = a.weapon.fire_interval if a.weapon else 0.12

    # ------------------------------------------------------------ 难度

    def _apply_tune(self):
        base = C.AI_PRESETS[self.difficulty]
        k = 1.0 + self.adapt * C.AI_ADAPT_BAND      # adapt>0 → 敌人更难

        # 敌人按所选难度（含自适应）来。
        self.enemy_tune = dict(
            reaction=base["reaction"] / k,
            sigma=base["sigma"] / k,
            burst=clamp(base["burst"] * k, 0.0, 1.0),
            strafe=clamp(base["strafe"] * k, 0.0, 1.0),
            move_mul=base["move_mul"] * (1.0 + (k - 1.0) * 0.5),
        )

        # 队友（我方 AI）固定"靠谱队友"档，不随敌人难度缩放——难度由敌人决定，
        # 玩家才是主角。比 normal 敌人略强，保证玩家手感一般（=实际 2v3）时队友
        # 也能扛住 3 个敌人，而不是和敌人同水平导致 2v3 必败。
        self.ally_tune = dict(C.AI_ALLY_TUNE)

    def _adapt(self):
        """逐回合调难度（不逐帧）：赢且有人头 → 加压；输且死得早 → 放水。"""
        k = self.stats["kills"] - self._last_k
        d = self.stats["deaths"] - self._last_d
        self._last_k = self.stats["kills"]
        self._last_d = self.stats["deaths"]

        s = 0.5 if self.round_result == "win" else (-0.5 if self.round_result == "lose" else 0.0)
        s += 0.3 * (k - d)
        self.perf = self.perf * 0.6 + clamp(s, -1.0, 1.0) * 0.4
        self.adapt += (clamp(self.perf, -1.0, 1.0) - self.adapt) * C.AI_ADAPT_RATE
        self.adapt = clamp(self.adapt, -1.0, 1.0)
        self._apply_tune()

    # ------------------------------------------------------------ 回合

    def start_round(self):
        self.round_no += 1
        self.state = "prep"
        self.timer = C.MATCH_BUY_TIME
        self.live_t = 0.0
        self.round_result = None
        self.player_dead = False
        self.player_hp = C.PLAYER_HP
        self.spectate = None

        for a in self.agents:
            a.alive = True
            a.hp = C.AGENT_HP
            a.flash = 0.0
            a.target = None
            a.path = []
            a.goal_cell = None
            a.last_seen = None
            a.lost_timer = 0.0
            a.react = 0.0
            a.fire_cd = 0.0
            a.burst_left = 0
            a.muzzle = 0.0
            a.roam = None
            a.smoke_charges = 0
            a.smoke_cd = 0.0
            a.smoke_intent = 0.0
            a.smoke_aim = None
            a.respawn_timer = 0.0
            a.invuln = 0.0
            a.crouch = False
            a.h = C.BOT_H

        self._place_all()

        # AI 买枪
        for a in self.agents:
            if not a.is_player:
                self._ai_buy(a)

    # ------------------------------------------------------------ 积分赛（TDM）

    def _start_score(self):
        """积分赛开局：无回合、无经济，全员直接上，状态恒 live。"""
        self.state = "live"
        self.timer = 0.0
        self.live_t = 0.0
        self.round_result = None
        self.player_dead = False
        self.player_hp = C.PLAYER_HP
        self.spectate = None
        for a in self.agents:
            a.alive = True
            a.hp = C.AGENT_HP
            a.flash = 0.0
            a.target = None
            a.path = []
            a.goal_cell = None
            a.last_seen = None
            a.lost_timer = 0.0
            a.react = 0.0
            a.fire_cd = 0.0
            a.burst_left = 0
            a.muzzle = 0.0
            a.roam = None
            a.smoke_charges = 0
            a.smoke_cd = 0.0
            a.smoke_intent = 0.0
            a.smoke_aim = None
            a.respawn_timer = 0.0
            a.invuln = 0.0
            a.crouch = False
            a.h = C.BOT_H
            if not a.is_player:
                # 免费配枪：默认步枪（积分赛无经济，玩家用 1-5 自由换）
                a.weapon = match_weapon("rifle")
        self._place_all()
        self.team_kills = [0, 0]
        self.player_respawn = 0.0

    def _respawn(self, a: Agent):
        """阵亡单位重生到本队出生点，带一段无敌时间。玩家重生会同步 player_hp。"""
        base = self.spawns[a.team]
        # 出生点周围稍微散开，避免叠在一起互相卡住
        ox = self.rng.uniform(-1.5, 1.5)
        oy = self.rng.uniform(-1.5, 1.5)
        a.x, a.y = base[0] + ox, base[1] + oy
        a.alive = True
        a.hp = C.AGENT_HP
        a.flash = 0.0
        a.target = None
        a.path = []
        a.goal_cell = None
        a.last_seen = None
        a.lost_timer = 0.0
        a.react = 0.0
        a.fire_cd = 0.0
        a.burst_left = 0
        a.muzzle = 0.0
        a.roam = None
        a.smoke_charges = C.SMOKE_AI_SCORE_CHARGES if self.mode == "score" else 0
        a.smoke_cd = 0.0
        a.smoke_intent = 0.0
        a.smoke_aim = None
        a.respawn_timer = 0.0
        a.crouch = False
        a.h = C.BOT_H
        a.invuln = C.SCORE_INVULN
        foe = self.spawns[1 - a.team]
        a.yaw = math.atan2(foe[1] - a.y, foe[0] - a.x)
        if a.is_player:
            self.player_hp = C.PLAYER_HP
            self.player_dead = False
            self.player_respawn = 0.0

    def _update_score(self, dt: float):
        for f in self.feed:
            f[2] -= dt
        self.feed = [f for f in self.feed if f[2] > 0]

        # 烟仍在走（积分赛默认没有烟，这里只是保险）
        self.smokes.update(dt, self.gmap)
        self._smoke_direct_hits()

        # 积分赛没有 prep/live 回合切换，这里手动累计「交火已进行时间」，
        # 供 AI 用烟的开局冷静期（SMOKE_AI_CALM）判断用。
        self.live_t += dt

        # 无敌倒计时 + 阵亡重生倒计时
        if self.player_dead:
            self.player_respawn -= dt
        for a in self.agents:
            if a.invuln > 0:
                a.invuln = max(0.0, a.invuln - dt)
            if not a.alive:
                a.respawn_timer -= dt
                if a.respawn_timer <= 0:
                    self._respawn(a)

        self._drive_humans(dt)

        for a in self.agents:
            tune = self.enemy_tune if a.team == 1 else self.ally_tune
            update_agent(self, a, dt, self.rng, tune)

        if (self.team_kills[0] >= C.SCORE_KILL_TARGET
                or self.team_kills[1] >= C.SCORE_KILL_TARGET):
            self.state = "match_end"

    def player_swap(self, key: str) -> bool:
        """积分赛里 1-5 自由换枪（无经济，不花一分钱）。

        顺手把换到的枪记进库存，这样联机快照和 HUD 读到的状态是一致的。
        """
        if key not in MATCH_WEAPONS:
            return False
        a = self.player_agent
        if key not in a.loadout:
            a.loadout.append(key)
        self._select(a, key)
        return True

    def update(self, dt: float):
        if self.mode == "score":
            self._update_score(dt)
            return
        for f in self.feed:
            f[2] -= dt
        self.feed = [f for f in self.feed if f[2] > 0]

        # 烟一直在走（买枪阶段扔的烟也会在交火时展开）
        self.smokes.update(dt, self.gmap)
        # 飞行中的烟弹直击敌人 → 造成伤害（落地变烟后不再造成伤害，且非友伤）
        self._smoke_direct_hits()

        if self.state == "prep":
            self.timer -= dt
            if self.timer <= 0:
                self.state = "live"
                self.timer = C.MATCH_ROUND_TIME
                self.live_t = 0.0

        elif self.state == "live":
            self.timer -= dt
            self.live_t += dt
            self._drive_humans(dt)
            for a in self.agents:
                tune = self.enemy_tune if a.team == 1 else self.ally_tune
                update_agent(self, a, dt, self.rng, tune)
            self._check_elimination()
            if self.state == "live" and self.timer <= 0:
                self._timeout()

        elif self.state == "round_end":
            self.timer -= dt
            if self.timer <= 0:
                done = (self.score[0] >= C.MATCH_WINS_NEEDED
                        or self.score[1] >= C.MATCH_WINS_NEEDED
                        or self.round_no >= C.MATCH_MAX_ROUNDS)
                if done:
                    self.state = "match_end"
                else:
                    self.start_round()

    def _alive(self, team: int) -> int:
        return sum(1 for a in self.agents if a.team == team and a.alive)

    def _check_elimination(self):
        a0, a1 = self._alive(0), self._alive(1)
        if a1 == 0 and a0 == 0:
            self._end_round(None)
        elif a1 == 0:
            self._end_round(0)
        elif a0 == 0:
            self._end_round(1)

    def _timeout(self):
        """时间到：存活人数多的一方赢，相同算平局（双方都不得分）。"""
        a0, a1 = self._alive(0), self._alive(1)
        if a0 > a1:
            self._end_round(0, reason="人数优势")
        elif a1 > a0:
            self._end_round(1, reason="人数优势")
        else:
            self._end_round(None, reason="时间到 · 人数相同")

    def _end_round(self, winner, reason=""):
        self.state = "round_end"
        self.timer = C.MATCH_END_PAUSE
        if winner is None:
            self.round_result = "draw"
            self._award(0, lost=True)
            self._award(1, lost=True)
            self.feed_add(f"平局  {reason}", C.C_DIM)
        else:
            self.score[winner] += 1
            self.round_result = "win" if winner == 0 else "lose"
            self._award(winner, lost=False)
            self._award(1 - winner, lost=True)
            tag = "回合胜利" if winner == 0 else "回合失败"
            self.feed_add(f"{tag}  {reason}", C.C_ALLY_HUD if winner == 0 else C.C_ENEMY_HUD)
        self._adapt()

    # ------------------------------------------------------------ 经济

    def _loss_bonus(self, team: int) -> int:
        s = self.loss_streak[team]
        return min(C.ECON_LOSS_BASE + C.ECON_LOSS_STEP * max(0, s - 1), C.ECON_LOSS_MAX)

    def _award(self, team: int, lost: bool):
        if lost:
            self.loss_streak[team] = min(self.loss_streak[team] + 1, 5)
            amount = self._loss_bonus(team)
        else:
            self.loss_streak[team] = 0
            amount = C.ECON_WIN
        for a in self.agents:
            if a.team != team:
                continue
            if a.is_player:
                self.player_money = min(C.ECON_MAX, self.player_money + amount)
            else:
                a.money = min(C.ECON_MAX, a.money + amount)

    def _select(self, a, key: str) -> bool:
        """切到库存里已有的某把枪。库存里没有就返回 False（不花钱、不改状态）。

        切枪本身不受回合阶段限制 —— 买枪阶段和交火中都能切，否则会出现
        "买了两把枪却切不回去"的尴尬。
        """
        if key not in a.loadout:
            return False
        a.weapon = MATCH_WEAPONS[key]
        a.w_idx = a.loadout.index(key)
        return True

    def player_select(self, key: str) -> bool:
        """玩家切换到已拥有的武器（1-5 键）。没买过返回 False。"""
        return self._select(self.player_agent, key)

    def _buy(self, a, key: str, money: int | None = None):
        """买枪：已经拥有就免费切过去（不重复扣钱），否则扣钱入库并装备。"""
        w = MATCH_WEAPONS[key]
        if key in a.loadout:
            self._select(a, key)
            return True
        if money is None:
            money = a.money
        if money < w.price:
            return False
        if a.is_player:
            self.player_money -= w.price
        else:
            a.money -= w.price
        a.loadout.append(key)
        a.weapon = w
        a.w_idx = a.loadout.index(key)
        return True

    def _ai_buy(self, a):
        """AI 买枪 + 买烟。队友和敌人都用同一套，所以两边都会扔烟。

        已经有步枪就不再重复买（库存里留着就能一直用），省下的钱去买烟 ——
        否则 AI 每回合都重新买一把步枪，经济永远攒不起来。
        """
        if "rifle" in a.loadout:
            pass          # 主武器还在（回合之间不清空），这回合不用再买
        elif a.money >= MATCH_WEAPONS["rifle"].price:
            self._buy(a, "rifle")
        elif ("smg" not in a.loadout and self.rng.random() < 0.65
              and a.money >= MATCH_WEAPONS["smg"].price):
            self._buy(a, "smg")
        # 都买不起就保留开局的手枪（无需 rebuy）

        # 烟雾弹：有钱就买，最多带 2 颗（避免囤货把经济榨干），
        # 这样无论队友（队0）还是敌人（队1）都会在对战里真正用烟。
        while a.smoke_charges < 2 and a.money >= C.SMOKE_PRICE:
            a.money -= C.SMOKE_PRICE
            a.smoke_charges += 1

    def player_buy(self, key: str) -> bool:
        if self.state != "prep":
            return False
        return self._buy(self.player_agent, key, money=self.player_money)

    def player_buy_smoke(self) -> bool:
        """买枪阶段花 $SMOKE_PRICE 买一颗烟雾弹（实际携带量由 Game 维护）。"""
        if self.state != "prep":
            return False
        if self.player_money < C.SMOKE_PRICE:
            return False
        self.player_money -= C.SMOKE_PRICE
        return True

    # ------------------------------------------------------------ 投掷物伤害

    def _smoke_direct_hits(self):
        """飞行中的烟弹若擦到敌人（非友伤），造成一次 SMOKE_DIRECT_DMG。"""
        for g in self.smokes.grenades:
            # 只在"还没起烟"的飞行段判定；起烟后变成遮蔽烟，不再造成伤害
            if g.resting or g._popped:
                continue
            for a in self.agents:
                if not a.alive or a.team == g.team or id(a) in g.hit_ids:
                    continue
                if math.hypot(g.x - a.x, g.y - a.y) < C.SMOKE_HIT_R:
                    g.hit_ids.add(id(a))
                    self.apply_smoke_damage(a, C.SMOKE_DIRECT_DMG, g.team)

    def apply_smoke_damage(self, tgt, dmg: float, thrower_team: int):
        """烟雾弹直击伤害：非友伤；对玩家走 player_hp，对 AI 走 agent.hp。"""
        if tgt.team == thrower_team:
            return
        if tgt.invuln > 0:
            return
        if tgt.is_player:
            self.player_hp -= dmg
            tgt.hp = self.player_hp
            tgt.flash = 1.0
            if self.player_hp <= 0:
                self.player_hp = 0
                tgt.alive = False
                self.stats["deaths"] += 1
                self.player_dead = True
                if self.mode == "score":
                    self.player_respawn = C.SCORE_RESPAWN_DELAY
                    tgt.respawn_timer = C.SCORE_RESPAWN_DELAY
                    self.team_kills[thrower_team] += 1
                tgt.deaths += 1
                self.feed_add("你被烟雾弹炸到", C.C_ENEMY_HUD)
            return
        tgt.hp -= dmg
        tgt.flash = 1.0
        if tgt.hp <= 0:
            tgt.alive = False
            tgt.target = None
            tgt.deaths += 1
            if self.mode == "score":
                self.team_kills[thrower_team] += 1
                tgt.respawn_timer = C.SCORE_RESPAWN_DELAY
            self.feed_add("敌人被烟雾弹炸伤", C.C_ALLY_HUD)

    # ------------------------------------------------------------ 伤害

    def apply_damage(self, shooter, tgt, head: bool):
        if tgt.invuln > 0:           # 重生无敌期间免伤（积分赛）
            return
        w = shooter.weapon if shooter is not None else match_weapon("rifle")
        dmg = w.damage * (w.headshot_mul if head else 1.0)

        if tgt.is_player:
            # 玩家的血量存在 Match 上，影子 Agent 只是给 AI 当瞄准目标用的
            self.player_hp -= dmg
            tgt.hp = self.player_hp
            tgt.flash = 1.0
            if self.player_hp > 0:
                return
            self.player_hp = 0
            tgt.alive = False
            self.stats["deaths"] += 1
            self.player_dead = True
            tgt.deaths += 1
            if self.mode == "score":
                self.player_respawn = C.SCORE_RESPAWN_DELAY
                tgt.respawn_timer = C.SCORE_RESPAWN_DELAY
                if shooter is not None:
                    self.team_kills[shooter.team] += 1
            self.feed_add(f"你被 {w.name} {'爆头' if head else '击倒'}", C.C_ENEMY_HUD)
            return

        tgt.hp -= dmg
        tgt.flash = 1.0
        if tgt.hp > 0:
            return

        tgt.alive = False
        tgt.target = None
        tgt.deaths += 1
        if self.mode == "score":
            if shooter is not None:
                self.team_kills[shooter.team] += 1
            # 排好重生倒计时；不设的话 _update_score 里 respawn_timer<=0 会让它瞬间复活
            tgt.respawn_timer = C.SCORE_RESPAWN_DELAY

        killer_is_player = shooter is not None and shooter.is_player
        if shooter is not None:
            shooter.kills += 1
        if killer_is_player:
            self.stats["kills"] += 1
            if self.mode != "score":
                self.player_money = min(C.ECON_MAX, self.player_money + w.kill_reward)
            who = "你"
            col = C.C_ALLY_HUD
        else:
            if shooter is not None and self.mode != "score":
                shooter.money = min(C.ECON_MAX, shooter.money + w.kill_reward)
            # 死的是敌人 → 我方得分新闻；死的是队友 → 用敌方色
            who = "队友" if tgt.team == 1 else "敌人"
            col = C.C_ALLY_HUD if tgt.team == 1 else C.C_ENEMY_HUD
        tag = "爆头" if head else "击倒"
        self.feed_add(f"{who} {tag} · {w.name}", col)

    def on_shot_missed(self, a):
        pass

    # ------------------------------------------------------------ 辅助

    def feed_add(self, text: str, color):
        self.feed.append([text, color, FEED_TTL])
        if len(self.feed) > 5:
            self.feed.pop(0)

    def sync_player(self, cam):
        """把玩家的真实位置/血量同步给影子 Agent —— 敌人 AI 是靠这个影子
        发现并瞄准你的，所以每帧都要同步，而且必须在 m.update() 之前调。"""
        p = self.player_agent
        # 阵亡观战时相机会贴到队友身上，这里不能再跟着相机走，
        # 否则"尸体"会被拖到队友位置（alive 已为 False，但位置仍然要留在死亡点）。
        if not self.player_dead:
            p.x, p.y = cam.x, cam.y
        p.hp = self.player_hp
        p.alive = not self.player_dead

    def enemies(self):
        """玩家能打的目标（队 1 的活人）。不开友伤。"""
        return [a for a in self.agents if a.team == 1 and a.alive]

    def visible_agents(self):
        """渲染用：除玩家影子外的所有 Agent，藏在烟里的不画（烟是双向封视线的）。"""
        return [a for a in self.agents
                if not a.is_player and not self.smokes.hides(a.x, a.y)]

    def spectate_target(self):
        """阵亡后观战：优先还活着的队友。"""
        mates = [a for a in self.agents if a.team == 0 and a.alive and not a.is_player]
        return mates[0] if mates else None

    @property
    def match_over(self) -> bool:
        return self.state == "match_end"

    @property
    def player_won(self) -> bool:
        if self.mode == "score":
            return self.team_kills[0] > self.team_kills[1]
        return self.score[0] > self.score[1]

    # ------------------------------------------------------------ 联机快照

    def snapshot(self) -> dict:
        """把全场状态压成可 JSON 化的字典，发给客户端。"""
        ags = []
        for i, a in enumerate(self.agents):
            ags.append(dict(
                id=i, uid=a.uid, team=a.team, x=round(a.x, 3), y=round(a.y, 3),
                yaw=round(a.yaw, 4), z=round(a.z, 3),
                hp=round(a.hp, 1), alive=a.alive, crouch=a.crouch,
                flash=round(a.flash, 2), muzzle=round(a.muzzle, 2),
                invuln=round(a.invuln, 2),
                # 用武器 key（不是中文名）同步，否则客户端还原时找不到对应武器
                weapon=(a.weapon.key if a.weapon else "rifle"),
                loadout=list(a.loadout), w_idx=a.w_idx,
                controller=a.controller, is_local=a.is_player, name=a.name,
                kills=a.kills, deaths=a.deaths, shots=a.shots, hits=a.hits,
                smoke_charges=a.smoke_charges,
            ))
        return dict(
            mode=self.mode,
            team_kills=self.team_kills[:],
            score=self.score[:],
            player_hp=round(self.player_hp, 1),
            player_dead=self.player_dead,
            player_respawn=round(self.player_respawn, 2),
            state=self.state,
            feed=[[t, list(c), round(ttl, 2)] for t, c, ttl in self.feed],
            stats=dict(self.stats),
            agents=ags,
            smokes=self.smokes.snapshot(),
        )

    def apply_snapshot(self, snap: dict):
        """客户端：用主机快照刷新本地状态（不模拟，只渲染/交互）。"""
        ags_in = snap["agents"]
        for ad in ags_in:
            i = ad["id"]
            while i >= len(self.agents):
                na = Agent(ad["team"], ad["x"], ad["y"])
                na.controller = ad["controller"]
                na.is_player = ad["is_local"]
                na.uid = ad["uid"]
                self.agents.append(na)
            a = self.agents[i]
            a.team = ad["team"]
            a.uid = ad["uid"]
            a.x, a.y, a.yaw, a.z = ad["x"], ad["y"], ad["yaw"], ad["z"]
            a.hp, a.alive = ad["hp"], ad["alive"]
            a.crouch, a.flash, a.muzzle = ad["crouch"], ad["flash"], ad["muzzle"]
            a.invuln = ad["invuln"]
            a.controller, a.is_player = ad["controller"], ad["is_local"]
            a.name = ad["name"]
            # 主机发的是武器 key（如 "rifle"）；练习武器（pr_*）兜底成步枪
            wkey = ad.get("weapon", "rifle")
            a.weapon = MATCH_WEAPONS.get(wkey, match_weapon(wkey))
            a.loadout = list(ad.get("loadout") or ["pistol"])
            a.w_idx = int(ad.get("w_idx", 0) or 0)
            if a.w_idx >= len(a.loadout):
                a.w_idx = 0
            a.kills = ad.get("kills", 0)
            a.deaths = ad.get("deaths", 0)
            a.shots = ad.get("shots", 0)
            a.hits = ad.get("hits", 0)
            a.smoke_charges = ad.get("smoke_charges", 0)
        # 掉线的真人其 Agent 不再出现在快照里 → 截掉，避免残影
        if len(self.agents) > len(ags_in):
            self.agents = self.agents[:len(ags_in)]
        # 把本地玩家指向快照里标记为 is_local 的 Agent（联机客户端会再覆盖成自己的 uid）
        for a in self.agents:
            if a.is_player:
                self.player_agent = a
                break
        self.team_kills = snap["team_kills"][:]
        self.score = snap["score"][:]
        self.player_hp = snap["player_hp"]
        self.player_dead = snap["player_dead"]
        self.player_respawn = snap["player_respawn"]
        self.state = snap["state"]
        # kill feed 是主机视角写的（"你被..."指主机玩家）；客户端收到时
        # 把「你」改写成「主机」，不然读起来像自己死了。
        self.feed = [[t.replace("你", "主机"), tuple(c), ttl]
                     for t, c, ttl in snap["feed"]]
        self.stats = dict(snap["stats"])
        self.smokes.apply_snapshot(snap["smokes"])
