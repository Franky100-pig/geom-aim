"""玩家：移动碰撞、后坐力、弹道扩散、开火节奏。"""

from __future__ import annotations

import math

import pygame

import config as C
from engine import clamp
from weapons import practice_rifle, practice_sniper

# 简化的 AK 风格弹道：前几发几乎直上，随后往右摆、再往左回
SPRAY_YAW_PATTERN = (
    0.00, 0.18, 0.42, 0.72, 1.00, 1.10, 0.95, 0.60,
    0.10, -0.45, -0.85, -1.00, -0.85, -0.55, -0.20, 0.15,
    0.45, 0.55, 0.40, 0.15, -0.10, -0.30, -0.35, -0.25,
)

BURST_RESET = 0.32   # 松手多久算新的一轮点射


class Player:
    def __init__(self):
        self.vx = 0.0
        self.vy = 0.0
        self.recoil_px = 0.0
        self.recoil_yaw_px = 0.0
        self.burst = 0
        self.since_shot = 99.0
        self.cooldown = 0.0
        self.firing = False
        self.moving = False
        self.kick = 0.0
        self.bob = 0.0
        self.shots = 0
        self.hits = 0
        # —— 狙击相关（仅 SNIPER 模式由 Game 设置 ads；其余模式保持 False）——
        self.ads = False       # 是否正在开镜
        self.bolt = 0.0        # 栓动剩余冷却；>0 时不能开火
        # —— 跳跃：只抬高相机，不碰碰撞/命中判定，所以跳起来躲不掉子弹 ——
        self.z = 0.0           # 离地高度（世界单位；墙高 = 1.0）
        self.vz = 0.0
        self.airborne = False
        # —— 蹲（Ctrl 按住）：下沉相机 + 收紧扩散 + 缩小命中轮廓 ——
        self.crouch = False
        # 当前武器。练习模式默认这把的数值逐项等于 config 里的常量，
        # 所以接进来之后 5 个练习模式的手感一个像素都没变。
        self.weapon = practice_rifle()

    def set_practice_weapon(self, mode: str):
        """练习模式：狙击模式换栓动+4x 镜那把，其余用步枪。"""
        self.weapon = practice_sniper() if mode == "sniper" else practice_rifle()

    # ------------------------------------------------------------ 移动

    def update_move(self, dt, cam, gmap, keys):
        self.crouch = bool(keys[pygame.K_LCTRL] or keys[pygame.K_RCTRL])
        fwd = (1 if keys[pygame.K_w] else 0) - (1 if keys[pygame.K_s] else 0)
        stf = (1 if keys[pygame.K_d] else 0) - (1 if keys[pygame.K_a] else 0)

        dx, dy = math.cos(cam.yaw), math.sin(cam.yaw)
        px, py = -math.sin(cam.yaw), math.cos(cam.yaw)
        wx = dx * fwd + px * stf
        wy = dy * fwd + py * stf
        n = math.hypot(wx, wy)
        if n > 1e-6:
            wx, wy = wx / n, wy / n

        if n > 1e-6:
            maxv = C.MOVE_SPEED * (C.SNIPER_MOVE_MUL if self.ads else 1.0)
            k = min(1.0, C.ACCEL * dt / maxv)
            self.vx += (wx * maxv - self.vx) * k
            self.vy += (wy * maxv - self.vy) * k
        else:
            f = max(0.0, 1.0 - C.FRICTION * dt)
            self.vx *= f
            self.vy *= f

        # 分轴推进 → 贴墙自动滑行
        nx = cam.x + self.vx * dt
        if not gmap.blocked(nx, cam.y, C.PLAYER_RADIUS):
            cam.x = nx
        else:
            self.vx = 0.0
        ny = cam.y + self.vy * dt
        if not gmap.blocked(cam.x, ny, C.PLAYER_RADIUS):
            cam.y = ny
        else:
            self.vy = 0.0

        speed = math.hypot(self.vx, self.vy)
        self.moving = speed > 0.7
        self.bob += speed * dt * 2.4

    # ------------------------------------------------------------ 跳跃

    def try_jump(self) -> bool:
        """地面上才能起跳；空中不吃二次输入（没有二段跳）。"""
        if self.airborne or self.z > 0.0:
            return False
        self.vz = C.JUMP_SPEED
        self.airborne = True
        return True

    def update_jump(self, dt: float):
        """重力积分：起跳 → 到顶 → 落回地面。落地当帧 airborne 就复位。"""
        if not self.airborne:
            self.z = 0.0
            self.vz = 0.0
            return
        self.vz -= C.JUMP_GRAVITY * dt
        self.z += self.vz * dt
        if self.z <= 0.0:
            self.z = 0.0
            self.vz = 0.0
            self.airborne = False

    # ------------------------------------------------------------ 武器

    @property
    def spread(self) -> float:
        w = self.weapon
        s = w.spray_first + min(self.burst, 24) * w.spray_per_shot
        if self.moving:
            s += w.move_spray
        if self.airborne:
            s += C.AIR_SPRAY      # 滞空惩罚：跳着扫基本打不中
        if self.crouch:
            s *= C.CROUCH_SPRAY_MUL   # 蹲下更稳
        return min(s, w.spray_max + w.move_spray + C.AIR_SPRAY)

    def can_fire(self) -> bool:
        return self.cooldown <= 0.0

    def on_shot(self):
        w = self.weapon
        self.cooldown = w.fire_interval
        self.shots += 1
        self.burst += 1
        self.since_shot = 0.0
        self.kick = 1.0
        self.recoil_px = min(C.RECOIL_MAX_PX, self.recoil_px + w.recoil_px)
        idx = min(self.burst - 1, len(SPRAY_YAW_PATTERN) - 1)
        self.recoil_yaw_px = clamp(
            self.recoil_yaw_px + SPRAY_YAW_PATTERN[idx] * w.recoil_yaw_px,
            -C.RECOIL_MAX_PX, C.RECOIL_MAX_PX)

    # —— 狙击：单发 + 栓动 ——
    def can_bolt_fire(self) -> bool:
        """栓动就绪：上栓冷却结束才能开火。"""
        return self.bolt <= 0.0

    def on_sniper_shot(self):
        """一发栓动射击：记录射击、轻微上抬、进入上栓冷却。

        后坐力打折和栓动时长都来自武器本身（练习狙击那把是 RECOIL_PX*0.4 /
        BOLT_TIME，对战的 AWP 是 16px / 0.9s），所以两种模式共用这一条路径。
        """
        self.shots += 1
        self.since_shot = 0.0
        self.kick = 1.0
        self.recoil_px = min(C.RECOIL_MAX_PX, self.recoil_px + self.weapon.recoil_px)
        self.bolt = self.weapon.bolt_time
        self.cooldown = 0.0

    def update_weapon(self, dt, renderer_h: float):
        self.cooldown = max(0.0, self.cooldown - dt)
        self.bolt = max(0.0, self.bolt - dt)
        self.since_shot += dt
        if self.since_shot > BURST_RESET:
            self.burst = 0

        scale = renderer_h / 720.0
        rec = C.RECOIL_RECOVER_PX * scale * dt
        self.recoil_px = max(0.0, self.recoil_px - rec)
        self.recoil_yaw_px -= clamp(self.recoil_yaw_px, -rec, rec)
        self.kick = max(0.0, self.kick - dt * 9.0)

    def apply_to_camera(self, cam, renderer):
        scale = renderer.h / 720.0
        yaw_rad = self.recoil_yaw_px * scale / (renderer.h * renderer.vscale)
        cam.apply_recoil(yaw_rad, self.recoil_px * scale)
