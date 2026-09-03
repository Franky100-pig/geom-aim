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
from engine import clamp
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

        for a in self.agents:
            tune = self.enemy_tune if a.team == 1 else self.ally_tune
            update_agent(self, a, dt, self.rng, tune)

        if (self.team_kills[0] >= C.SCORE_KILL_TARGET
                or self.team_kills[1] >= C.SCORE_KILL_TARGET):
            self.state = "match_end"

    def player_swap(self, key: str) -> bool:
        """积分赛里 1-5 自由换枪（无经济，不花一分钱）。"""
        if key not in MATCH_WEAPONS:
            return False
        self.player_agent.weapon = MATCH_WEAPONS[key]
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

    def _buy(self, a, key: str, money: int | None = None):
        w = MATCH_WEAPONS[key]
        if money is None:
            money = a.money
        if money < w.price:
            return False
        if a.is_player:
            self.player_money -= w.price
        else:
            a.money -= w.price
        a.weapon = w
        return True

    def _ai_buy(self, a):
        """AI 买枪 + 买烟。队友和敌人都用同一套，所以两边都会扔烟。"""
        if a.money >= MATCH_WEAPONS["rifle"].price:
            self._buy(a, "rifle")
        elif a.money >= MATCH_WEAPONS["smg"].price and self.rng.random() < 0.65:
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
                self.feed_add("你被烟雾弹炸到", C.C_ENEMY_HUD)
            return
        tgt.hp -= dmg
        tgt.flash = 1.0
        if tgt.hp <= 0:
            tgt.alive = False
            tgt.target = None
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
        if self.mode == "score":
            if shooter is not None:
                self.team_kills[shooter.team] += 1
            # 排好重生倒计时；不设的话 _update_score 里 respawn_timer<=0 会让它瞬间复活
            tgt.respawn_timer = C.SCORE_RESPAWN_DELAY

        killer_is_player = shooter is not None and shooter.is_player
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
