"""GEOM AIM —— 伪 3D 第一人称练枪房 + 3v3 回合制对战 + 5v5 积分赛 + 局域网联机。

运行：  python3 main.py
标题界面： 1 练习模式    2 对战 3v3    3 积分赛 5v5    4 创建房间    5 加入房间    [ ] 调 AI 难度
练习：     WASD 移动 / 鼠标 转视角 / 左键 开火 / 右键 轻点开关镜（SNIPER）/ 1-5 换模式
对战：     买枪阶段 1-5 买枪 / 左键 开火 / 右键 开镜 / ESC 菜单 / H 返回主菜单
积分赛：   5v5 连续重生 TDM，1-5 自由换枪，先到 25 杀获胜 / Ctrl 蹲 / H 返回主菜单
局域网：   4 建房（人类 vs AI，最多 3 人），5 输入主机 IP 或 xxx.local 加入
"""

from __future__ import annotations

import math
import os
import random
import socket
import sys
import time

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

import pygame  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config as C  # noqa: E402
import hud  # noqa: E402
from audio import Audio  # noqa: E402
from effects import Effects  # noqa: E402
from engine import Camera, Renderer, build_arena, cast_ray, cast_ray_block  # noqa: E402
from match import Match  # noqa: E402
from nades import SmokeField  # noqa: E402
from net import Client, Host  # noqa: E402
from player import Player  # noqa: E402
from targets import MODE_HINT, MODE_KEYS, MODE_NAMES, Range  # noqa: E402
from weapons import BUY_ORDER, MATCH_WEAPONS  # noqa: E402

DIFF_ORDER = ("easy", "normal", "hard", "expert")
DIFF_NAMES = {"easy": "简单", "normal": "普通", "hard": "困难", "expert": "专家"}


def _lerp_angle(a: float, b: float, t: float) -> float:
    """沿最短路径把角度 a 插值到 b，避免跨 ±pi 时绕一大圈。"""
    d = (b - a + math.pi) % math.tau - math.pi
    return a + d * t


def _smoothstep(t: float) -> float:
    t = 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)
    return t * t * (3.0 - 2.0 * t)


class Game:
    def __init__(self):
        pygame.init()
        flags = pygame.DOUBLEBUF
        try:
            self.screen = pygame.display.set_mode((C.WINDOW_W, C.WINDOW_H),
                                                  flags, vsync=1)
        except Exception:
            self.screen = pygame.display.set_mode((C.WINDOW_W, C.WINDOW_H), flags)
        pygame.display.set_caption("GEOM AIM")
        self.clock = pygame.time.Clock()
        self.fullscreen = False

        self.renderer = Renderer(C.WINDOW_W, C.WINDOW_H, C.H_FOV_DEG)
        self.gmap = build_arena(C.ARENA_TILES_X, C.ARENA_TILES_Y,
                                C.ARENA_ROOM_W, C.ARENA_ROOM_H)
        spawn = self.gmap.center_free()
        self.cam = Camera(spawn[0], spawn[1])
        self.player = Player()
        self.range = Range(self.gmap, random.Random())
        self.fx = Effects()
        self.audio = Audio()

        # 烟雾弹：练习和对战共用同一个烟场（切模式时清空重来）。
        # 弹药和冷却归"人"管，SmokeField 只管物理。
        self.smokes = SmokeField()
        self.smoke_left = C.SMOKE_PRACTICE_MAX
        self.smoke_cd = 0.0

        self.sens = C.MOUSE_SENS
        self.hfov = C.H_FOV_DEG
        self.crosshair = 0

        # title = 开局选模式；play = 游戏中（练习和对战共用）；menu = ESC 暂停
        self.state = "title"
        self.match: Match | None = None
        self.difficulty = C.AI_DIFF_DEFAULT
        self._last_round = 0
        self._reset_death_cam()     # 倒地计时 / 观战目标 / 朝向插值进度
        self.running = True

        # 局域网联机状态
        self.net_mode = "none"      # "none" | "host" | "client"
        self.host = None
        self.client = None
        self.lobby_names: list = []
        self.join_text = ""
        self._net_acc = 0.0
        self._pend_look = 0.0       # 待上行的鼠标 yaw 增量（客户端用）
        self.client_weapon = "rifle"
        self._smoke_pending = False  # 客户端 G 键边沿（一次性上报）
        self.connect_error = ""
        self.score = 0
        self.combo = 0
        self.best_combo = 0
        self.combo_timer = 0.0
        self.hit_count = 0
        self.hint_alpha = 1.0
        self.hint_hold = 5.0
        self.fps_smooth = 60.0

        # 标题界面：不抓鼠标（要看得到光标、能选），背后用 botz 当静态预览背景
        self._grab(False)
        self.range.set_mode("botz", self.cam)
        self.player.set_practice_weapon("botz")

    # ------------------------------------------------------------ 进入模式

    def start_practice(self, mode: str = "botz"):
        self.match = None
        # 回到练习：重建大拼接地图，并把 Range 的地图引用也指回来
        # （Range 在构造时缓存了 gmap，不重绑会继续用对战的小地图）。
        self.gmap = build_arena(C.ARENA_TILES_X, C.ARENA_TILES_Y,
                                C.ARENA_ROOM_W, C.ARENA_ROOM_H)
        self.range.gmap = self.gmap
        self.cam.x, self.cam.y = self.gmap.center_free()
        self.player.ads = False
        self.renderer.set_zoom(1.0)
        self.smokes.clear()
        self.smoke_left = C.SMOKE_PRACTICE_MAX
        self.smoke_cd = 0.0
        self.range.set_mode(mode, self.cam)
        self.player.set_practice_weapon(self.range.mode)
        self.score = 0
        self.combo = 0
        self.combo_timer = 0.0
        self.hit_count = 0
        self.hint_alpha = 1.0
        self.hint_hold = 5.0
        self.state = "play"
        self._grab(True)

    def start_match(self):
        """开一局 3v3：建一张小地图（比练习小得多，很快能碰面）、重置玩家状态、
        建 Match，进入买枪阶段。self.gmap 换成小地图，渲染/射击/AI 全用它。"""
        self.gmap = build_arena(C.MATCH_TILES_X, C.MATCH_TILES_Y,
                                C.MATCH_ROOM_W, C.MATCH_ROOM_H, cover=True)
        self.smokes.clear()
        self.smoke_left = 0          # 对战烟雾弹靠经济买，开局 0 颗
        self.smoke_cd = 0.0
        self.match = Match(self.gmap, random.Random(), self.difficulty, self.smokes)
        self.player.ads = False
        self.renderer.set_zoom(1.0)
        self.player.weapon = self.match.player_agent.weapon   # 开局手枪
        self.player.burst = 0
        self.player.cooldown = 0.0
        self.player.bolt = 0.0
        self.player.firing = False
        self.player.recoil_px = 0.0
        self.player.recoil_yaw_px = 0.0
        self._last_round = 0          # 让首帧把镜头摆回我方出生点
        self._snap_to_spawn()
        self.state = "play"
        self._grab(True)

    def _reset_death_cam(self):
        """阵亡镜头状态归位：倒地计时、当前观战目标、朝向插值进度。"""
        self.death_t = 0.0
        self._spec_agent = None
        self._spec_blend = 1.0
        self._spec_yaw0 = 0.0

    def _snap_to_spawn(self):
        """把玩家镜头摆回我方出生点、朝向敌方出生点。
        每回合开局（以及刚进对战）都要做，否则死之后观战队友，镜头会卡在队友
        位置上，复活时人直接刷在墙里或地图另一头。"""
        self._reset_death_cam()
        if self.match is None:
            return
        sp = self.match.spawns[0]
        foe = self.match.spawns[1]
        self.cam.x, self.cam.y = sp[0], sp[1]
        self.cam.yaw = math.atan2(foe[1] - sp[1], foe[0] - sp[0])
        self.cam.pitch_px = 0.0
        self.player.vx = self.player.vy = 0.0

    def start_score(self, seed=None):
        """开一局 5v5 积分赛（连续重生 TDM）：3×3 大地图、无经济、可随时换枪、
        阵亡短暂延迟后带 3 秒无敌重生，先累计 25 杀的队伍获胜。你是 5 人之一。

        seed：地图随机种子。传入则掩体布局可复现（联机主机用，便于客户端
        按同一颗种子重建完全相同的地图）；不传则每局随机。
        """
        arena_rng = random.Random(seed) if seed is not None else random.Random()
        self.gmap = build_arena(C.SCORE_MAP_TILES_X, C.SCORE_MAP_TILES_Y,
                                C.SCORE_MAP_ROOM_W, C.SCORE_MAP_ROOM_H,
                                rng=arena_rng, cover=True)
        self.smokes.clear()
        self.smoke_left = C.SMOKE_AI_SCORE_CHARGES   # 积分赛：与 AI/客户端真人一致，开局 1 颗
        self.smoke_cd = 0.0
        self.smoke_cd = 0.0
        self.match = Match(self.gmap, random.Random(), self.difficulty, self.smokes, mode="score")
        self.player.ads = False
        self.renderer.set_zoom(1.0)
        self.player.weapon = self.match.player_agent.weapon   # 开局手枪
        self.player.burst = 0
        self.player.cooldown = 0.0
        self.player.bolt = 0.0
        self.player.firing = False
        self.player.recoil_px = 0.0
        self.player.recoil_yaw_px = 0.0
        self._player_was_dead = False
        self._snap_to_spawn()
        self.state = "play"
        self._grab(True)

    # ------------------------------------------------------------ 局域网联机

    def _close_net(self):
        if self.host is not None:
            self.host.close()
            self.host = None
        if self.client is not None:
            try:
                self.client.leave()
            except Exception:
                pass
            self.client = None
        self.net_mode = "none"
        self.lobby_names = []

    def start_host(self):
        """创建局域网房间（人类 vs AI，最多 3 人，空位补 AI）。"""
        self._host_seed = random.randint(0, (1 << 31) - 1)
        self.start_score(seed=self._host_seed)  # 建 5v5 积分赛 + 权威 Match
        self.host = Host(self.gmap, self.match, seed=self._host_seed, cover=True)
        self.net_mode = "host"
        self.lobby_names = []
        self.connect_error = ""
        self.state = "host_lobby"               # 等朋友加入，按 Enter 开局
        self._grab(False)

    def _start_host_play(self):
        self.state = "play"
        self._grab(True)

    def start_client(self, host_str: str):
        """加入局域网房间：host_str 可以是 IP 或 Frankys-Mac.local 这类主机名。"""
        self.connect_error = ""
        c = Client(host_str.strip(), name="你")
        welcome = c.connect(timeout=5.0)
        if welcome is None:
            self.connect_error = "连接失败：主机未开 / 地址错 / 房间已满"
            try:
                c.leave()
            except Exception:
                pass
            self.state = "title"
            self._grab(False)
            return
        # 客户端不传整张网格：按主机给的种子 + 尺寸确定性重建同一张地图
        g = build_arena(welcome["tiles_x"], welcome["tiles_y"],
                        welcome["room_w"], welcome["room_h"],
                        rng=random.Random(welcome["seed"]),
                        cover=welcome.get("cover", True))
        self.gmap = g
        # 客户端不跑模拟，Match 只作数据容器，每帧被快照覆盖
        self.match = Match(g, random.Random(), self.difficulty, self.smokes, mode="score")
        self.client = c
        self.client_uid = welcome.get("uid", 0)   # 主机分配的、专属于本机的 Agent 编号
        self.net_mode = "client"
        self.client_weapon = "rifle"
        self.state = "client"
        self._grab(True)

    def _update_host(self, dt: float):
        self._update_score_match(dt)           # 主机本地玩家走原流程
        self._net_acc += dt
        if self._net_acc >= 1.0 / C.NET_TICK_HZ:
            self._net_acc = 0.0
            if self.host is not None:
                self.host.broadcast(self.match.snapshot())

    def _update_client(self, dt: float):
        c = self.client
        if c is None:
            return
        # 断线检测：超过 NET_TIMEOUT 没收到主机的任何包就回标题，
        # 否则主机退出/崩溃后客户端永远停在最后一帧画面上。
        if time.time() - c.last_recv > C.NET_TIMEOUT:
            self.to_title()
            self.connect_error = "与主机断开连接（超时）"
            return
        keys = pygame.key.get_pressed()
        mbt = pygame.mouse.get_pressed()
        mvx = (1 if keys[pygame.K_w] else 0) - (1 if keys[pygame.K_s] else 0)
        mvy = (1 if keys[pygame.K_d] else 0) - (1 if keys[pygame.K_a] else 0)
        crouch = bool(keys[pygame.K_LCTRL] or keys[pygame.K_RCTRL])
        jump = bool(keys[pygame.K_SPACE])
        fire = bool(mbt[0])
        smoke = self._smoke_pending
        self._smoke_pending = False
        inp = dict(mvx=mvx, mvy=mvy, crouch=crouch, jump=jump, fire=fire,
                   weapon=self.client_weapon, smoke=smoke, dyaw=self._pend_look)
        self._pend_look = 0.0

        self._net_acc += dt
        if self._net_acc >= 1.0 / C.NET_INPUT_HZ:
            self._net_acc = 0.0
            c.send_input(inp)

        was_dead = self.match.player_dead
        c.pump()
        if c.snap is not None:
            self.match.apply_snapshot(c.snap)
        # 联机客户端要跟随「自己这台机器」对应的 Agent，而不是主机玩家。
        # 主机在 welcome 里给了本机专属 uid，快照里每个 Agent 带 uid，据此定位。
        me = None
        for a in self.match.agents:
            if getattr(a, "uid", None) == self.client_uid:
                me = a
                break
        if me is not None:
            self.match.player_agent = me
            self.match.player_dead = not me.alive
            self.match.player_hp = me.hp
            # 烟雾槽 UI 与真实弹药数同步（服务端权威）
            self.smoke_left = me.smoke_charges
            self.smoke_cd = me.smoke_cd
        if self.match.player_dead != was_dead:
            self._reset_death_cam()

        m = self.match
        la = me if me is not None else m.player_agent
        if not m.player_dead:
            self.cam.x, self.cam.y = la.x, la.y
            self.cam.yaw = la.yaw                       # yaw 取服务器权威值
            self.cam.z = la.z - (C.CROUCH_EYE_DROP if la.crouch else 0.0)
            self.cam.apply_recoil(0.0, 0.0)
            self.player.crouch = la.crouch
            self.player.weapon = la.weapon
            # ads 是本地视觉状态（右键切换），这里只负责缩放过渡；
            # 阵亡才强制收镜。
            self.renderer.lerp_zoom(self.player.weapon.zoom
                                    if self.player.ads else 1.0, dt)
        else:
            self.player.ads = False
            s = m.spectate_target()
            self._dead_camera(dt, s)
            m.spectate = s if self.death_t >= C.DEATH_CAM_HOLD else None
            self.player.firing = False
        self.fx.update(dt)

    def to_title(self):
        """返回标题界面：退出当前练习 / 对战，回到选模式界面，并释放鼠标。

        对战里 self.gmap 换成了小地图，而标题背景（botz 预览）用的是练习大地图，
        所以这里必须把大地图重建回来，否则回到标题会停在上一局的小地图上。
        玩家、连击、烟雾、缩放全部归位，等效于刚启动程序时的标题状态。
        """
        self._close_net()
        self.match = None
        self.gmap = build_arena(C.ARENA_TILES_X, C.ARENA_TILES_Y,
                                C.ARENA_ROOM_W, C.ARENA_ROOM_H)
        self.range.gmap = self.gmap
        spawn = self.gmap.center_free()
        self.cam = Camera(spawn[0], spawn[1])
        self.player = Player()                       # 干净重置：武器/跳跃/连击/开火全归位
        self.range.set_mode("botz", self.cam)
        self.player.set_practice_weapon("botz")
        self.smokes.clear()
        self.smoke_left = C.SMOKE_PRACTICE_MAX
        self.smoke_cd = 0.0
        self._reset_death_cam()
        self.renderer.set_zoom(1.0)
        self.score = 0
        self.combo = 0
        self.best_combo = 0
        self.combo_timer = 0.0
        self.hit_count = 0
        self.state = "title"
        self._grab(False)

    # ------------------------------------------------------------ 鼠标

    def _grab(self, on: bool):
        pygame.mouse.set_visible(not on)
        try:
            pygame.event.set_grab(on)
        except Exception:
            pass
        if on:
            pygame.mouse.get_rel()

    # ------------------------------------------------------------ 查询

    def mode_name(self) -> str:
        return MODE_NAMES[self.range.mode]

    def mode_hint(self) -> str:
        return MODE_HINT[self.range.mode]

    def combo_multiplier(self) -> float:
        # 首杀不给加成，从第二连击开始爬，封顶 2.5x
        return 1.0 + min(max(0, self.combo - 1), C.COMBO_CAP) * C.COMBO_STEP

    # ------------------------------------------------------------ 主循环

    def run(self):
        while self.running:
            dt = min(self.clock.tick(C.FPS_CAP) / 1000.0, 0.05)
            cur = self.clock.get_fps()
            self.fps_smooth += (cur - self.fps_smooth) * 0.06

            self.handle_events()
            if self.net_mode == "host":
                self.host.poll()
                self.lobby_names = self.host.names()
                # 权威服务器不能暂停：主机开 ESC 菜单时模拟与广播必须继续，
                # 否则所有客户端画面冻结。单机才能靠菜单暂停。
                if self.state in ("play", "menu"):
                    self._update_host(dt)
            elif self.net_mode == "client":
                self._update_client(dt)
            elif self.state == "play":
                self.update(dt)
            self.draw()
        pygame.quit()

    # ------------------------------------------------------------ 事件

    def handle_events(self):
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                self.running = False
                return

            # 加入房间：在这里拦截所有按键，做地址输入
            if self.state == "join_input":
                if ev.type == pygame.KEYDOWN:
                    if ev.key == pygame.K_ESCAPE:
                        self.state = "title"
                        self._grab(False)
                    elif ev.key == pygame.K_RETURN:
                        if self.join_text.strip():
                            self.start_client(self.join_text)
                    elif ev.key == pygame.K_BACKSPACE:
                        self.join_text = self.join_text[:-1]
                    elif ev.unicode and ev.unicode.isprintable() and len(self.join_text) < 48:
                        self.join_text += ev.unicode
                continue

            elif ev.type in (pygame.WINDOWFOCUSLOST, pygame.WINDOWMINIMIZED):
                # 切到别的窗口 / 最小化时放开鼠标。不然鼠标被 grab 锁在窗口里，
                # 焦点又不在游戏上，动都动不了。
                # 注意 pygame 2 用的是扁平事件类型，没有 SDL 那种
                # WINDOWEVENT + .event 子属性（写成那样会 AttributeError）。
                if self.state == "play":
                    self.state = "menu"
                    self.player.firing = False
                    self.player.ads = False
                    self.renderer.set_zoom(1.0)
                    self._grab(False)
                elif self.state == "client":
                    # 客户端没有菜单态：只放开鼠标，点回窗口时再抓（MOUSEBUTTONDOWN）
                    self._grab(False)

            elif ev.type == pygame.MOUSEMOTION:
                # 单机（none）和主机（host）都走本地 look()：主机跑权威模拟，
                # 自己就是普通玩家。只有客户端（client）走「上行增量」路线。
                if self.state == "play" and self.net_mode in ("none", "host"):
                    self.look(ev.rel[0], ev.rel[1])
                elif self.state == "client":
                    # 客户端：yaw 交给服务器，这里只累积待上行的 yaw 增量，
                    # 并本地直接改俯仰（pitch 纯视觉，服务器不需要）。
                    eff = self.sens * (C.SNIPER_SENS_MUL if self.player.ads else 1.0)
                    self._pend_look += ev.rel[0] * eff
                    sign = 1.0 if C.INVERT_Y else -1.0
                    self.cam.pitch_px += sign * ev.rel[1] * eff * self.renderer.h * self.renderer.vs
                    limit = C.PITCH_LIMIT * self.renderer.h
                    self.cam.pitch_px = max(-limit, min(limit, self.cam.pitch_px))

            elif ev.type == pygame.MOUSEBUTTONDOWN:
                if self.state == "client":
                    # 客户端：右键本地开镜（纯视觉），左键点回窗口时重新抓鼠标
                    if ev.button == 3:
                        self.player.ads = not self.player.ads
                    elif ev.button == 1:
                        self._grab(True)
                    continue
                if self.state != "play":
                    continue
                if ev.button == 1:
                    if self.match is not None:
                        self._match_press()      # 对战：按武器类型决定单发/连发/栓动
                    elif self.range.mode == "sniper":
                        self.fire_sniper()        # 狙击：每次点击单发，由栓动控制节奏
                    else:
                        self.player.firing = True
                        self.player.cooldown = 0.0   # 点击即响，不等冷却
                elif ev.button == 3:
                    # 右键轻点开关镜：狙击练习模式 + 对战模式都行
                    if self.match is not None or self.range.mode == "sniper":
                        self.player.ads = not self.player.ads

            elif ev.type == pygame.MOUSEBUTTONUP:
                if ev.button == 1:
                    self.player.firing = False
                # 右键已改为「轻点切换」，松开不再改 ads，否则会和切换逻辑冲突


            elif ev.type == pygame.KEYDOWN:
                self.on_key(ev.key)

    def look(self, dx: int, dy: int):
        # 阵亡观战期间视角锁定在队友身上，鼠标一律不参与。
        # 鼠标事件写的是 cam.yaw / cam.pitch_px 这两个"基准值"，而渲染读的是
        # eff_yaw / eff_pitch_px；对战里 apply_to_camera 又排在阵亡分支之前，
        # 于是每一下鼠标移动都被算进 eff_* 里，画面就跟着甩。
        if self.match is not None and self.match.player_dead:
            return
        cam, r = self.cam, self.renderer
        # 开镜时灵敏度乘子（倍率越大越稳）。其余模式不受影响。
        eff = self.sens * (C.SNIPER_SENS_MUL if self.player.ads else 1.0)
        cam.yaw += dx * eff
        # pygame 的 rel[1] 鼠标上移为负。pitch_px 为正 = 视角上抬，
        # 所以正常（INVERT_Y=False）时系数为 -1，使「鼠标上移→视角上抬」。
        # 用 r.vs（受 zoom 影响的有效缩放）保证开镜后俯仰的像素→角度一致。
        sign = 1.0 if C.INVERT_Y else -1.0
        cam.pitch_px += sign * dy * eff * r.h * r.vs
        limit = C.PITCH_LIMIT * r.h
        cam.pitch_px = max(-limit, min(limit, cam.pitch_px))
        cam.yaw %= math.tau

    def _dead_camera(self, dt: float, s):
        """阵亡后的镜头：先向后倒，停留 DEATH_CAM_HOLD 秒再切到队友第一视角。

        * 倒地：位置不动，眼高平滑落到地面、视线逐渐仰起——最后对着天空
          （pitch_px 为正 = 视线上抬，见 look() 里的注释）。
        * 观战：完全贴合队友，位置 / 朝向 / 俯仰全跟随，并且 eff_* 一起写——
          渲染读的是 eff_yaw / eff_pitch_px，只写基准值是不生效的。
        * 全程鼠标不参与（look() 已拦掉），所以不会再一动鼠标画面就甩。
        """
        cam = self.cam
        self.death_t += dt

        # —— 倒地阶段：还没到切视角的时间，或场上没有可观的队友 ——
        if s is None or self.death_t < C.DEATH_CAM_HOLD:
            k = _smoothstep(self.death_t / C.DEATH_FALL_TIME)
            scale = self.renderer.h / 720.0
            cam.z = (C.DEATH_EYE_H - C.EYE_HEIGHT) * k
            cam.pitch_px = C.DEATH_SKY_PITCH_PX * scale * k
            cam.eff_yaw = cam.yaw
            cam.eff_pitch_px = cam.pitch_px
            return

        # —— 观战阶段：完全贴合队友 ——
        cam.x, cam.y = s.x, s.y
        cam.z = 0.0
        if s is not self._spec_agent:              # 换人了，起一段朝向插值
            self._spec_agent = s
            self._spec_yaw0 = cam.yaw
            self._spec_blend = 0.0
        if self._spec_blend < 1.0:
            self._spec_blend = min(1.0, self._spec_blend
                                   + dt / C.SPEC_SWITCH_TIME)
            cam.yaw = _lerp_angle(self._spec_yaw0, s.yaw,
                                  _smoothstep(self._spec_blend))
        else:
            cam.yaw = s.yaw
        cam.pitch_px = 0.0
        cam.eff_yaw = cam.yaw
        cam.eff_pitch_px = 0.0

    def _match_press(self):
        """对战模式按下左键：栓动/半自动走单发，全自动交给 update 连发。"""
        m, p = self.match, self.player
        if m.state != "live" or m.player_dead:
            return
        w = p.weapon
        if w.bolt_time > 0:
            self.fire_sniper()                 # AWP：一发一拉栓
        elif not w.auto:
            if p.can_fire():
                p.on_shot()
                self._do_shot()                # 手枪 / 连狙：每次点击一发
        else:
            p.firing = True
            p.cooldown = 0.0

    def on_key(self, key):
        # ---------- 任意状态：H 返回标题（练习/对战/暂停菜单都行） ----------
        if key == pygame.K_h:
            self.to_title()
            return

        # ---------- 房间主人：开局 / 取消 ----------
        if self.state == "host_lobby":
            if key in (pygame.K_RETURN, pygame.K_SPACE):
                self._start_host_play()
            elif key == pygame.K_ESCAPE:
                self.to_title()
            return

        # ---------- 客户端（键盘只管换枪 / 扔烟 / 退出） ----------
        if self.net_mode == "client" and self.state == "client":
            if pygame.K_1 <= key <= pygame.K_5:
                idx = key - pygame.K_1
                if idx < len(BUY_ORDER):
                    self.client_weapon = BUY_ORDER[idx]
                    w = MATCH_WEAPONS.get(self.client_weapon)
                    if w:
                        self.player.weapon = w
                    self.audio.play("spawn")
                return
            if key == pygame.K_g:
                self._smoke_pending = True
                return
            if key == pygame.K_ESCAPE:
                self.to_title()
            return

        # ---------- 标题界面 ----------
        if self.state == "title":
            if key == pygame.K_1:
                self.start_practice("botz")
            elif key == pygame.K_2:
                self.start_match()
            elif key == pygame.K_3:
                self.start_score()
            elif key == pygame.K_4:
                self.start_host()
            elif key == pygame.K_5:
                self.state = "join_input"
                self.join_text = ""
                self._grab(False)
            elif key in (pygame.K_LEFTBRACKET, pygame.K_RIGHTBRACKET):
                d = -1 if key == pygame.K_LEFTBRACKET else 1
                i = DIFF_ORDER.index(self.difficulty)
                self.difficulty = DIFF_ORDER[max(0, min(len(DIFF_ORDER) - 1, i + d))]
            elif key == pygame.K_q:
                self.running = False
            return

        # ---------- 积分赛：1-5 随时自由换枪（无经济） ----------
        if self.match is not None and self.match.mode == "score":
            if pygame.K_1 <= key <= pygame.K_5:
                idx = key - pygame.K_1
                if idx < len(BUY_ORDER):
                    if self.match.player_swap(BUY_ORDER[idx]):
                        self.player.weapon = self.match.player_agent.weapon
                        self.player.bolt = 0.0
                        self.audio.play("spawn")
                return
            if key == pygame.K_6:
                return  # 积分赛不配烟雾弹

        # ---------- 对战：买枪阶段 1-5 买枪，6 买烟雾弹 ----------
        if self.match is not None and self.match.state == "prep":
            if pygame.K_1 <= key <= pygame.K_5:
                idx = key - pygame.K_1
                if idx < len(BUY_ORDER):
                    w = BUY_ORDER[idx]
                    ok = self.match.player_buy(w)
                    if ok:
                        self.player.weapon = self.match.player_agent.weapon
                        self.player.bolt = 0.0
                        self.audio.play("spawn")
                    else:
                        self.fx.popup(self.renderer.w * 0.5, self.renderer.h * 0.60,
                                      "钱不够", C.C_WARN)
                return
            if key == pygame.K_6:
                if self.match.player_buy_smoke():
                    self.smoke_left += 1
                    self.audio.play("spawn")
                else:
                    self.fx.popup(self.renderer.w * 0.5, self.renderer.h * 0.60,
                                  "钱不够", C.C_WARN)
                return

        if key == pygame.K_ESCAPE:
            self.state = "menu" if self.state == "play" else "play"
            self._grab(self.state == "play")
            if self.state == "play":
                self.player.firing = False
            else:
                # 进菜单时退出开镜并复位缩放，避免卡在放大状态
                self.player.ads = False
                self.renderer.set_zoom(1.0)
            return

        if key == pygame.K_q and self.state == "menu":
            self.running = False
            return

        # 对战模式下 1-5 是买枪，不能拿去切练习模式
        if self.match is None and pygame.K_1 <= key <= pygame.K_9:
            idx = key - pygame.K_1
            if 0 <= idx < len(MODE_KEYS):
                self.set_mode(MODE_KEYS[idx])
            return

        if key == pygame.K_r:
            if self.match is not None:
                # 打完了就再来一局；回合进行中 R 不生效，免得误触重开。
                # 联机主机不能 R：重开会新建 Match+新地图种子，Host 还持旧
                # 引用，客户端会卡在旧比赛/错地图上。联机打完按 H 收房。
                if self.match.match_over and self.net_mode != "host":
                    if self.match.mode == "score":
                        self.start_score()
                    else:
                        self.start_match()
            else:
                self.range.set_mode(self.range.mode, self.cam)
            self.combo = 0
            self.combo_timer = 0.0
            return

        # ---------- 通用动作：空格跳 / G 扔烟 ----------
        if self.state == "play" and key == pygame.K_SPACE:
            self.player.try_jump()
            return

        if self.state == "play" and key == pygame.K_g:
            self._throw_smoke()
            return

        # 灵敏度在「游戏中」和「菜单里」都能调 —— 之前挡在菜单守卫后面，
        # 游戏里按 [ ] 是零反应；而且固定步长 ±0.0002 在默认 0.0022 附近
        # 只有约 9%，连按十次才翻倍，体感几乎察觉不到。
        if key == pygame.K_LEFTBRACKET:
            self.bump_sens(1.0 / C.SENS_STEP)
            return
        if key == pygame.K_RIGHTBRACKET:
            self.bump_sens(C.SENS_STEP)
            return

        # 下面这些只在菜单里调
        if self.state != "menu":
            if key == pygame.K_f:
                self.toggle_fullscreen()
            return

        if key in (pygame.K_MINUS, pygame.K_KP_MINUS):
            self.set_fov(self.hfov - 5.0)
        elif key in (pygame.K_EQUALS, pygame.K_KP_PLUS):
            self.set_fov(self.hfov + 5.0)
        elif key == pygame.K_c:
            self.crosshair = (self.crosshair + 1) % 3
        elif key == pygame.K_m:
            self.audio.toggle_mute()
        elif key == pygame.K_l:
            self.reload_palette()
        elif key == pygame.K_f:
            self.toggle_fullscreen()

    def bump_sens(self, factor: float):
        """按乘法倍率调灵敏度，并弹一个屏幕提示。

        游戏里没有那个菜单数字可看，不弹提示的话玩家根本不知道调没调上。
        """
        self.sens = max(C.SENS_MIN, min(C.SENS_MAX, self.sens * factor))
        self.fx.popup(self.renderer.w * 0.5, self.renderer.h * 0.62,
                      f"灵敏度  {self.sens * 1000:.2f}", C.C_ACCENT, big=True)

    def reload_palette(self):
        """热重载配色：改完 config.py 不用重启，切菜单按 L 就能看到效果。

        天花板/地板渐变是启动时烤进 Surface 的，改颜色不重建就看不到。
        注意所有模块都是 `import config as C` + `C.XXX` 访问，reload 后新值
        立刻生效 —— 要是哪天写成 `from config import C_WALL` 这招就失灵了。
        """
        import importlib

        # reload 会把整个 config 重置成文件里的值，玩家在游戏里调过的
        # 灵敏度 / FOV / 准星得先存起来再还回去
        saved = (self.sens, self.hfov, self.crosshair)
        importlib.reload(C)
        self.sens, self.hfov, self.crosshair = saved

        self.renderer.set_viewport(self.renderer.w, self.renderer.h, self.hfov)
        self.fx.popup(self.renderer.w * 0.5, self.renderer.h * 0.60,
                      "PALETTE RELOADED", C.C_ACCENT, big=True)

    def set_mode(self, mode: str):
        self.range.set_mode(mode, self.cam)
        self.player.set_practice_weapon(self.range.mode)   # 狙击模式换栓动那把
        self.player.ads = False          # 切模式时退出开镜
        self.renderer.set_zoom(1.0)      # 复位缩放，避免卡在放大状态
        self.combo = 0
        self.combo_timer = 0.0
        self.hint_alpha = 1.0
        self.hint_hold = 3.0
        if self.state in ("menu", "title"):
            self.state = "play"
            self._grab(True)

    def set_fov(self, deg: float):
        self.hfov = max(55.0, min(120.0, deg))
        self.renderer.set_viewport(self.renderer.w, self.renderer.h, self.hfov)

    def toggle_fullscreen(self):
        try:
            self.fullscreen = not self.fullscreen
            if self.fullscreen:
                self.screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
            else:
                self.screen = pygame.display.set_mode((C.WINDOW_W, C.WINDOW_H))
            self.renderer.set_viewport(*self.screen.get_size(), self.hfov)
        except Exception:
            self.fullscreen = False

    # ------------------------------------------------------------ 更新

    def update(self, dt: float):
        if self.match is not None:
            if self.match.mode == "score":
                self._update_score_match(dt)
            else:
                self._update_match(dt)
            return
        keys = pygame.key.get_pressed()
        self.player.update_move(dt, self.cam, self.gmap, keys)
        self.player.update_jump(dt)
        self.cam.z = self.player.z - (C.CROUCH_EYE_DROP if self.player.crouch else 0.0)
        self.player.update_weapon(dt, self.renderer.h)
        self.player.apply_to_camera(self.cam, self.renderer)

        # 狙击开镜：平滑过渡到放大倍率（松镜自动回 1）
        target_zoom = C.ADS_ZOOM if (self.player.ads and self.range.mode == "sniper") else 1.0
        self.renderer.lerp_zoom(target_zoom, dt)

        # 屏幕震动当作轻微视角抖动，比整屏位移便宜
        if self.fx.shake > 0.05:
            self.cam.eff_pitch_px += random.uniform(-1, 1) * self.fx.shake
            self.cam.eff_yaw += random.uniform(-1, 1) * self.fx.shake * 0.0004

        # 非狙击模式：按住左键持续连发（自动）。狙击模式的单发走 fire_sniper
        if self.range.mode != "sniper" and self.player.firing and self.player.can_fire():
            self.fire()

        events = self.range.update(dt, self.cam)
        for e in events:
            if e == "expire":
                self.break_combo()

        if self.combo > 0:
            self.combo_timer -= dt
            if self.combo_timer <= 0:
                self.break_combo()

        self.smokes.update(dt, self.gmap)
        if self.smoke_cd > 0.0:
            self.smoke_cd = max(0.0, self.smoke_cd - dt)

        self.fx.update(dt)

        if self.hint_hold > 0:
            self.hint_hold -= dt
        else:
            self.hint_alpha = max(0.0, self.hint_alpha - dt * 0.6)

    def break_combo(self):
        if self.combo > 1:
            self.audio.play("miss")
        self.combo = 0
        self.combo_timer = 0.0

    # ------------------------------------------------------------ 积分赛更新

    def _update_score_match(self, dt: float):
        m = self.match
        keys = pygame.key.get_pressed()

        # 玩家武器同步给影子 Agent；蹲下时缩小命中轮廓（更难被 AI 打中）
        m.player_agent.weapon = self.player.weapon
        m.player_agent.h = C.BOT_H * C.CROUCH_H_MUL if self.player.crouch else C.BOT_H
        m.sync_player(self.cam)

        was_dead = m.player_dead
        if not m.player_dead:
            self.player.update_move(dt, self.cam, self.gmap, keys)
            self.player.update_jump(dt)
            self.cam.z = self.player.z - (C.CROUCH_EYE_DROP if self.player.crouch else 0.0)
            self.player.update_weapon(dt, self.renderer.h)
            self.player.apply_to_camera(self.cam, self.renderer)
            self.renderer.lerp_zoom(self.player.weapon.zoom if self.player.ads else 1.0, dt)

            if self.fx.shake > 0.05:
                self.cam.eff_pitch_px += random.uniform(-1, 1) * self.fx.shake
                self.cam.eff_yaw += random.uniform(-1, 1) * self.fx.shake * 0.0004

            if (self.player.firing and self.player.weapon.auto
                    and self.player.can_fire()):
                self.fire()
        else:
            # 阵亡：先向后倒（视线最后朝天），到时间后由 _dead_camera 切到队友第一视角；
            # 重生计时到后由 m.update 内的 _respawn 拉起。
            # 这里刻意不调 apply_to_camera —— 那是玩家自己的后坐力，
            # 不该加到被观战队友的第一视角上。
            self.player.firing = False
            s = m.spectate_target()
            self._dead_camera(dt, s)
            m.spectate = s if self.death_t >= C.DEATH_CAM_HOLD else None
            self.player.update_weapon(dt, self.renderer.h)

        m.update(dt)

        # 死亡 / 重生的切换点：倒地计时与观战目标都要归位。
        # 刚死那一帧走的还是存活分支，所以倒地从下一帧才开始计时。
        if m.player_dead != was_dead:
            self._reset_death_cam()
            if not m.player_dead:
                self._snap_to_spawn()      # 刚复活：镜头摆回我方出生点
                # 积分赛重生补 1 颗烟，与 AI/客户端真人（_respawn 发弹）一致
                self.smoke_left = max(self.smoke_left, C.SMOKE_AI_SCORE_CHARGES)

        if self.smoke_cd > 0.0:
            self.smoke_cd = max(0.0, self.smoke_cd - dt)
        self.fx.update(dt)

    # ------------------------------------------------------------ 对战更新

    def _update_match(self, dt: float):
        m = self.match
        keys = pygame.key.get_pressed()

        # 新回合开局：把镜头摆回我方出生点（死过观战的话镜头会卡在队友处）
        if m.round_no != self._last_round:
            self._last_round = m.round_no
            self._snap_to_spawn()
            self.smoke_left = 0                   # 对战里烟雾弹改经济购买，每回合重新买
            self.smokes.clear()                   # 上回合的烟不留到这回合

        was_dead = m.player_dead
        if not m.player_dead:
            self.player.update_move(dt, self.cam, self.gmap, keys)
        self.player.update_jump(dt)
        # 阵亡观战队友时镜头贴队友的眼睛，不带玩家自己的跳跃高度
        self.cam.z = (self.player.z if not m.player_dead else 0.0) - (
            C.CROUCH_EYE_DROP if (not m.player_dead and self.player.crouch) else 0.0)
        self.player.update_weapon(dt, self.renderer.h)
        self.player.apply_to_camera(self.cam, self.renderer)
        # 蹲下时缩小命中轮廓（更难被 AI 打中）
        m.player_agent.h = C.BOT_H * C.CROUCH_H_MUL if self.player.crouch else C.BOT_H

        # 开镜倍率来自当前武器：步枪 1.0（等于没开），连狙 2x，AWP 4x
        self.renderer.lerp_zoom(self.player.weapon.zoom if self.player.ads else 1.0, dt)

        if self.fx.shake > 0.05:
            self.cam.eff_pitch_px += random.uniform(-1, 1) * self.fx.shake
            self.cam.eff_yaw += random.uniform(-1, 1) * self.fx.shake * 0.0004

        # 玩家的武器同步给影子 Agent，AI 打死你时才知道该记在哪把枪头上
        m.player_agent.weapon = self.player.weapon
        m.sync_player(self.cam)          # 必须在 m.update() 之前，AI 才看得到你

        # 全自动武器：按住左键连发。半自动/栓动由 _match_press 单点处理
        if (m.state == "live" and not m.player_dead and self.player.firing
                and self.player.weapon.auto and self.player.can_fire()):
            self.fire()

        m.update(dt)

        # 刚死 / 刚复活的那一帧：倒地计时与观战目标归位
        if m.player_dead != was_dead:
            self._reset_death_cam()

        # 阵亡后先向后倒（视线最后朝天），到时间再切到还活着的队友第一视角
        if m.player_dead:
            s = m.spectate_target()
            self._dead_camera(dt, s)
            m.spectate = s if self.death_t >= C.DEATH_CAM_HOLD else None
            self.player.firing = False

        # 烟由 m.update() 推进（Match 里已经调过 smokes.update），这里只管冷却
        if self.smoke_cd > 0.0:
            self.smoke_cd = max(0.0, self.smoke_cd - dt)

        self.fx.update(dt)

    # ------------------------------------------------------------ 投掷物

    def _throw_smoke(self):
        """按 G 扔烟：从眼睛高度朝准星方向抛物线扔出去。"""
        if self.smoke_cd > 0.0:
            return
        if self.match is not None and self.match.player_dead:
            return                      # 阵亡观战中扔不了
        if self.smoke_left <= 0:
            self.fx.popup(self.renderer.w * 0.5, self.renderer.h * 0.62,
                          "没烟了", C.C_WARN)
            return
        dx, dy = self.cam.dir()
        z = C.EYE_HEIGHT + self.cam.z
        if self.smokes.throw(self.cam.x, self.cam.y, z, dx, dy, team=0) is None:
            self.fx.popup(self.renderer.w * 0.5, self.renderer.h * 0.62,
                          "烟太多了", C.C_WARN)
            return
        self.smoke_left -= 1
        self.smoke_cd = C.SMOKE_COOLDOWN
        self.audio.play("spawn")

    # ------------------------------------------------------------ 开火

    def fire(self):
        # 普通武器：连发，走 AK 式后坐力
        self.player.on_shot()
        self._do_shot()

    def fire_sniper(self):
        # 狙击：先检查栓动是否就绪，单发后进入上栓冷却
        if not self.player.can_bolt_fire():
            return
        self.player.on_sniper_shot()
        self._do_shot()

    def _do_shot(self):
        p, cam, r = self.player, self.cam, self.renderer
        self.fx.add_muzzle()
        self.fx.add_shake(2.4)
        self.audio.play("shot")
        if self.match is not None:
            self.match.stats["shots"] += 1

        dx, dy = cam.dir()
        pux, puy = cam.plane_unit()
        spread = p.spread
        lat = random.uniform(-1.0, 1.0) * spread
        vert = random.uniform(-1.0, 1.0) * spread

        # 子弹从眼高飞出；低箱（0.70）比站立眼高（0.5）高，所以站在箱后打不穿、
        # 只有瞄着对方露出的上半身（更高的弹道）才能越过 —— 矮箱成了真掩体。
        eye_z = C.EYE_HEIGHT + cam.z

        best = None
        best_d = 1e9
        headshot = False
        # 对战时打的是敌方 Agent，练习时打的是靶子。其余几何一点没动。
        pool = self.match.enemies() if self.match is not None else self.range.targets
        for t in pool:
            rx, ry = t.x - cam.x, t.y - cam.y
            depth = rx * dx + ry * dy
            if depth <= 0.35 or depth >= best_d:
                continue
            lateral = rx * pux + ry * puy
            lat_eff = lateral + lat * depth
            if abs(lat_eff) > t.w * 0.5:
                continue
            h_aim = r.aim_height(cam, depth) + vert * depth
            if h_aim < 0.0 or h_aim > t.h:
                continue
            # 高度感知墙距：弹道从眼高飞向瞄准点，越过矮箱、撞满高墙
            slope = (h_aim - eye_z) / depth
            wall_d = cast_ray_block(self.gmap, cam.x, cam.y,
                                    dx + pux * lat, dy + puy * lat, eye_z, slope)
            if depth >= wall_d:
                continue
            # 矮箱后蹲下的目标看不见；满高掩体照旧挡视线
            if not self.gmap.clear_line_h(cam.x, cam.y, eye_z, t.x, t.y, t.h):
                continue
            scale = t.w / C.BOT_W
            head = (C.HEAD_BOT * t.h <= h_aim <= C.HEAD_TOP * t.h
                    and abs(lat_eff) <= C.HEAD_HALF_W * scale)
            best, best_d, headshot = t, depth, head

        # 弹着点在屏幕上的位置（与深度无关，只跟扩散有关）
        ix = r.w * 0.5 * (1.0 + lat / r.pl)
        iy = r.h * 0.5 - vert * r.h * r.vs
        mx, my = hud.muzzle_pos(r, p)
        self.fx.add_tracer(mx, my, ix, iy)

        if best is not None:
            self.on_hit(best, best_d, headshot, ix, iy)
        else:
            self.on_miss(ix, iy)

    def on_hit(self, t, depth, headshot, ix, iy):
        if self.match is not None:
            self._on_hit_match(t, headshot, ix, iy)
            return
        dmg = C.DAMAGE * (2.5 if headshot else 1.0)
        t.hp -= dmg
        t.flash = 1.0

        self.combo += 1
        self.best_combo = max(self.best_combo, self.combo)
        self.combo_timer = C.COMBO_TIMEOUT
        self.hit_count += 1
        self.range.register_hit()

        mult = self.combo_multiplier()
        base = C.SCORE_HEAD if headshot else C.SCORE_BODY
        gained = int(base * mult)
        self.score += gained

        # 屏幕位置：优先用靶子中心的投影，兜底用弹着点
        proj = self.renderer.project(self.cam, t.x, t.y, t.h * 0.6)
        sx, sy = (proj[0], proj[1]) if proj else (ix, iy)

        killed = t.hp <= 0 and t.kind != "track"
        self.fx.add_hitmark(headshot)
        self.audio.play("head" if headshot else "hit")
        self.fx.popup(sx, sy - 18, str(gained),
                      C.C_BOT_HEAD if headshot else C.C_TEXT, big=headshot)

        if killed:
            col = C.C_BOT_HEAD if headshot else C.C_BOT
            self.fx.burst(sx, sy, 22, col, speed=330.0, size=5.0)
            self.range.remove(t)
            self.audio.play("spawn")
        else:
            self.fx.burst(sx, sy, 7, C.C_BOT if not headshot else C.C_BOT_HEAD,
                          speed=170.0, size=3.2)

    def on_miss(self, ix, iy):
        self.fx.burst(ix, iy, 4, (150, 160, 180), speed=110.0, size=2.6,
                      gravity=900.0)
        if self.match is None:
            self.break_combo()

    def _on_hit_match(self, t, headshot, ix, iy):
        """对战模式的命中：伤害和金钱记在 Match 上，这里只管特效和音效。"""
        m = self.match
        m.stats["hits"] += 1
        if headshot:
            m.stats["headshots"] += 1

        proj = self.renderer.project(self.cam, t.x, t.y, t.h * 0.6)
        sx, sy = (proj[0], proj[1]) if proj else (ix, iy)

        self.fx.add_hitmark(headshot)
        self.audio.play("head" if headshot else "hit")

        col = C.C_ENEMY_HEAD if headshot else C.C_ENEMY
        m.apply_damage(m.player_agent, t, headshot)
        if not t.alive:
            self.fx.burst(sx, sy, 22, col, speed=330.0, size=5.0)
            self.audio.play("spawn")
        else:
            self.fx.burst(sx, sy, 7, col, speed=170.0, size=3.2)

    # ------------------------------------------------------------ 绘制

    def draw(self):
        r, cam, surf = self.renderer, self.cam, self.screen

        r.draw_sky_floor(surf, cam)
        r.draw_floor_grid(surf, cam, self.gmap)
        r.render_walls(surf, cam, self.gmap)

        # 从远到近画，保证近的挡住远的。人和烟混在同一个排序里：
        # 烟团是体积，只有按深度排才能正确地挡住它后面的人。
        # 关键：视线被烟挡住的 agent/靶子（在烟里、或在烟的另一侧）不画，
        # 否则玩家能透过烟看到对面的人。blocks() 与 AI 用的同一个判定。
        items = []
        if self.match is not None:
            for a in self.match.visible_agents():
                if a.alive and not self.smokes.blocks(cam.x, cam.y, a.x, a.y):
                    items.append((a.x, a.y, ("agent", a)))
        else:
            for t in self.range.targets:
                if not self.smokes.blocks(cam.x, cam.y, t.x, t.y):
                    items.append((t.x, t.y, ("target", t)))
        for g in self.smokes.grenades:
            if g.cloud_r > 0.0:
                items.append((g.cloud_x, g.cloud_y, ("smoke", g)))
            elif not g.resting:
                items.append((g.x, g.y, ("body", g)))

        for _x, _y, (kind, obj) in sorted(
                items, key=lambda it: -((it[0] - cam.x) ** 2 + (it[1] - cam.y) ** 2)):
            if kind == "smoke":
                self.smokes.draw_cloud(surf, r, cam, obj)
            elif kind == "body":
                self.smokes.draw_body(surf, r, cam, obj)
            elif kind == "agent":
                ally = (obj.team == 0)
                hud.draw_target(
                    surf, r, cam, obj,
                    body=(C.C_ALLY if ally else C.C_ENEMY),
                    head=(C.C_ALLY_HEAD if ally else C.C_ENEMY_HEAD),
                    edge=C.C_BOT_EDGE,
                )
            else:
                hud.draw_target(surf, r, cam, obj)

        self.fx.draw_world_fx(surf)
        hud.draw_weapon(surf, r, self.player)

        scoped = self.player.ads and (self.match is not None
                                      or self.range.mode == "sniper")
        if self.state in ("play", "client"):
            if scoped and self.player.weapon.zoom > 1.01:
                hud.draw_scope(surf, r, self.player)   # 开镜：圆形镜框 + 十字线，盖住普通准星
            else:
                hud.draw_crosshair(surf, r, self.player, self.crosshair)
            hud.draw_smoke_slot(surf, r, self)
        self.fx.draw_hud_fx(surf, hud.font(20), r.w * 0.5, r.h * 0.5)

        if self.match is not None:
            if self.match.mode == "score":
                hud.draw_score_hud(surf, r, self)
            else:
                hud.draw_match_hud(surf, r, self)
        else:
            hud.draw_scoreboard(surf, r, self)

        if self.state == "menu":
            hud.draw_menu(surf, r, self)
        elif self.state == "title":
            hud.draw_title(surf, r, self)
            if self.connect_error:
                # 断线 / 连接失败等提示：回到标题后仍然可见，直到下次连接
                hud.text(surf, self.connect_error, 18,
                         (r.w * 0.5, r.h * 0.86), C.C_ENEMY_HUD, anchor="cm")
        if self.state in ("menu", "title"):
            hud.text(surf, f"{self.fps_smooth:.0f} FPS", 14,
                     (r.w - 24, r.h - 26), C.C_DIM, anchor="br")

        if self.state == "host_lobby":
            self._draw_lobby(surf)
        elif self.state == "join_input":
            self._draw_join(surf)

        pygame.display.flip()

    # ------------------------------------------------------------ 联机界面

    def _draw_lobby(self, surf):
        w, h = self.renderer.w, self.renderer.h
        veil = pygame.Surface((w, h), pygame.SRCALPHA)
        veil.fill((6, 9, 15, 150))
        surf.blit(veil, (0, 0))
        hud.text(surf, "房间已创建 · 等待好友加入", 34, (w * 0.5, h * 0.22),
                 C.C_ACCENT, anchor="cm")
        lines = ["已加入："] + [f"  · {n}" for n in self.lobby_names] + ["（你 = 主机）"]
        y = h * 0.36
        for ln in lines:
            hud.text(surf, ln, 22, (w * 0.5, y), C.C_TEXT, anchor="cm")
            y += 34
        hud.text(surf, "按 Enter / 空格 开始对战", 24, (w * 0.5, h * 0.74),
                 C.C_ALLY_HUD, anchor="cm")
        hud.text(surf, "ESC 返回标题", 16, (w * 0.5, h * 0.80),
                 C.C_DIM, anchor="cm")
        ip = ""
        try:
            import net
            addrs = net.local_addresses()
            if addrs:
                ip = addrs[0]
        except Exception:
            pass
        if ip:
            hud.text(surf, f"好友请加入： {ip}   （或 {socket.gethostname()}.local）",
                     16, (w * 0.5, h * 0.88), C.C_DIM, anchor="cm")

    def _draw_join(self, surf):
        w, h = self.renderer.w, self.renderer.h
        veil = pygame.Surface((w, h), pygame.SRCALPHA)
        veil.fill((6, 9, 15, 200))
        surf.blit(veil, (0, 0))
        hud.text(surf, "加入局域网房间", 34, (w * 0.5, h * 0.30),
                 C.C_ACCENT, anchor="cm")
        hud.text(surf, "输入主机的 IP 或 xxx.local 主机名，回车连接：", 16,
                 (w * 0.5, h * 0.40), C.C_DIM, anchor="cm")
        box = pygame.Rect(int(w * 0.5 - 220), int(h * 0.46), 440, 44)
        pygame.draw.rect(surf, (30, 40, 60), box)
        pygame.draw.rect(surf, C.C_ACCENT, box, 2)
        hud.text(surf, self.join_text or "（在此输入）", 22,
                 (w * 0.5, h * 0.46 + 22), C.C_TEXT, anchor="cm")
        if self.connect_error:
            hud.text(surf, self.connect_error, 16, (w * 0.5, h * 0.62),
                     C.C_ENEMY_HUD, anchor="cm")
        hud.text(surf, "回车 连接    ESC 返回", 16, (w * 0.5, h * 0.70),
                 C.C_DIM, anchor="cm")


def main():
    print("GEOM AIM — 伪 3D 练枪房 + 3v3 对战 + 5v5 积分赛")
    print("  标题界面：  1 练习模式    2 对战 3v3    3 积分赛 5v5    [ ] 调 AI 难度")
    print("  练习：      WASD 移动  鼠标 转视角  左键 开火  右键 开关镜  1-5 换模式")
    print("  对战：      买枪阶段 1-5 买枪  左键 开火  右键 开镜  R（结束后）再来一局")
    print("  积分赛：    5v5 连续重生 TDM，1-5 自由换枪，先到 25 杀获胜，Ctrl 蹲")
    print("  通用：      ESC 菜单（灵敏度 / FOV / 准星 / 音效）  H 返回主菜单  M 静音  F 全屏")
    Game().run()


if __name__ == "__main__":
    main()
