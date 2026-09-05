"""武器数值表 + Weapon 对象。

设计约束（很重要）：
练习模式的默认武器，数值必须**逐项等于 config.py 里现有的常量**
（FIRE_INTERVAL / RECOIL_PX / SPRAY_* / DAMAGE / 爆头 2.5 倍 / 狙击 BOLT_TIME 与 ADS_ZOOM），
否则一接进来就会悄悄改掉 5 个练习模式的手感。所以这里用 C.* 直接构造，
不另写死数字 —— 以后调 config 的武器参数，练习模式跟着变，不会两边漂移。
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import config as C


@dataclass
class Weapon:
    key: str
    name: str
    price: int
    damage: float
    headshot_mul: float     # 爆头伤害倍率（无护甲，直接乘）
    fire_interval: float    # 两发之间的最小间隔（秒）
    auto: bool              # True = 按住连发；False = 半自动，每次点击一发
    bolt_time: float        # 栓动冷却；0 = 打完不用拉栓
    zoom: float             # 开镜倍率；1.0 = 不放大
    recoil_px: float        # 每发上抬（720p 基准像素）
    recoil_yaw_px: float    # 每发水平后坐基准
    spray_first: float      # 首发扩散（弧度）
    spray_per_shot: float   # 每发累加的扩散
    spray_max: float        # 扩散上限
    move_spray: float       # 移动中额外扩散
    kill_reward: int        # 击杀金钱奖励
    mag: int = 30           # 弹匣容量（发）；换弹一次补满，耗时 C.RELOAD_TIME


# ---------------------------------------------------------------- 练习模式

def practice_rifle() -> Weapon:
    """练习模式默认武器。数值 = 现在的 config 常量，保证 5 个练习模式手感不变。"""
    return Weapon(
        key="pr_rifle", name="步枪", price=0,
        damage=C.DAMAGE, headshot_mul=2.5,
        fire_interval=C.FIRE_INTERVAL, auto=True,
        bolt_time=0.0, zoom=1.0,
        recoil_px=C.RECOIL_PX, recoil_yaw_px=C.RECOIL_YAW_PX,
        spray_first=C.SPRAY_FIRST, spray_per_shot=C.SPRAY_PER_SHOT,
        spray_max=C.SPRAY_MAX, move_spray=C.MOVE_SPRAY,
        kill_reward=0, mag=30,
    )


def practice_sniper() -> Weapon:
    """狙击练习模式：在步枪基础上换成栓动 + 4x 镜 + 后坐力打四折。"""
    w = practice_rifle()
    return replace(w, key="pr_sniper", name="狙击",
                   bolt_time=C.BOLT_TIME, zoom=C.ADS_ZOOM,
                   recoil_px=C.RECOIL_PX * 0.4, mag=10)


# ---------------------------------------------------------------- 对战模式

# 平衡基准：血量 100、无护甲，所以爆头基本都是一枪带走，逼你抬头线。
# 价格/射击奖励照 CS 的量级来，方便直接理解。
MATCH_WEAPONS: dict[str, Weapon] = {
    "pistol": Weapon(
        key="pistol", name="手枪", price=300,
        damage=35.0, headshot_mul=4.0,          # 爆头 140，一枪秒
        fire_interval=0.16, auto=False,
        bolt_time=0.0, zoom=1.0,
        recoil_px=6.0, recoil_yaw_px=3.0,
        spray_first=0.0008, spray_per_shot=0.0012,
        spray_max=0.010, move_spray=0.0040,
        kill_reward=300,
        mag=12,
    ),
    "smg": Weapon(
        key="smg", name="冲锋枪", price=1400,
        damage=24.0, headshot_mul=4.2,          # 爆头 ~101，勉强一枪秒
        fire_interval=0.066, auto=True,          # 900 RPM
        bolt_time=0.0, zoom=1.0,
        recoil_px=5.0, recoil_yaw_px=4.0,
        spray_first=0.0025, spray_per_shot=0.0016,
        spray_max=0.020, move_spray=0.0038,
        kill_reward=600,
        mag=30,
    ),
    "rifle": Weapon(
        key="rifle", name="步枪", price=2700,
        damage=30.0, headshot_mul=4.0,          # 爆头 120，一枪秒
        fire_interval=0.10, auto=True,           # 600 RPM
        bolt_time=0.0, zoom=1.0,
        recoil_px=C.RECOIL_PX, recoil_yaw_px=C.RECOIL_YAW_PX,
        spray_first=C.SPRAY_FIRST, spray_per_shot=C.SPRAY_PER_SHOT,
        spray_max=C.SPRAY_MAX, move_spray=C.MOVE_SPRAY,
        kill_reward=300,
        mag=30,
    ),
    "dmr": Weapon(
        key="dmr", name="连狙", price=2200,
        damage=55.0, headshot_mul=2.0,          # 两枪身 / 一枪头
        fire_interval=0.28, auto=False,
        bolt_time=0.0, zoom=2.0,
        recoil_px=12.0, recoil_yaw_px=4.0,
        spray_first=0.0015, spray_per_shot=0.0010,
        spray_max=0.012, move_spray=0.0060,
        kill_reward=300,
        mag=20,
    ),
    "awp": Weapon(
        key="awp", name="狙击", price=4750,
        damage=100.0, headshot_mul=1.0,         # 打身体就是一枪
        fire_interval=0.10, auto=False,
        bolt_time=0.90, zoom=4.0,               # 栓动 + 4x 镜
        recoil_px=16.0, recoil_yaw_px=5.0,
        # 不开镜时扩散极大 —— 逼你真的开镜才打得中
        spray_first=0.0100, spray_per_shot=0.0,
        spray_max=0.0100, move_spray=0.0080,
        kill_reward=100,
        mag=5,
    ),
}

# 买枪菜单里的顺序（数字键 1-5）
BUY_ORDER = ("pistol", "smg", "rifle", "dmr", "awp")


def match_weapon(key: str) -> Weapon:
    return MATCH_WEAPONS.get(key, MATCH_WEAPONS["rifle"])
