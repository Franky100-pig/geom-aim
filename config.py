"""GEOM AIM —— 所有可调参数集中在这里。想改手感只动这个文件。"""

from __future__ import annotations

# ---------------- 窗口 ----------------
WINDOW_W = 1280
WINDOW_H = 720
FPS_CAP = 240          # 帧率上限（练枪游戏建议尽量高）
# 每根射线覆盖的像素宽度；越小越精细、越吃 CPU。
# 墙体光栅化实测（1280x720，CPU 侧）：1→2.3ms  2→1.14ms  3→0.76ms  4→0.70ms
# 默认 2：整帧约 1.5ms，画面几乎没有竖条纹。卡的话改成 3 或 4。
RENDER_COL_STEP = 2

# ---------------- 拼接式竞技场（很多房间直接拼成大地图）----------------
# 由 rx×ry 个「房间」直接拼成一张大地图：每个房间内部空旷、四壁围合，
# 相邻房间之间开门洞连通，外圈再封一圈外墙。地图越大，狙击越能拉出长视线、
# 走位越自由。改这几个数就能调场地规模（卡的话调小）。
ARENA_TILES_X = 4     # 横向房间数
ARENA_TILES_Y = 3     # 纵向房间数
ARENA_ROOM_W = 25     # 每个房间内部宽（格）—— 取奇数，让房间中心有整数坐标，整图严格 180° 对称
ARENA_ROOM_H = 17     # 每个房间内部高（格）

# ---------------- 视角 ----------------
H_FOV_DEG = 90.0       # 水平视场角（CS 味建议 90）
MOUSE_SENS = 0.0022    # 鼠标灵敏度（弧度 / 像素）
# [ ] 调灵敏度用「乘法步进」而不是加减固定值：加减法在低灵敏度区间每步体感
# 巨大、高区间几乎无感；乘法每步都是等比变化，感知均匀。1.12 ≈ 每步 12%，
# 按 6 次翻倍 / 减半，既跟手又不会一点就跳飞。
SENS_STEP = 1.12
SENS_MIN = 0.0004
SENS_MAX = 0.0100
PITCH_LIMIT = 0.35     # 上下可视角度上限（占屏幕高度的比例）
INVERT_Y = False

# ---------------- 移动 ----------------
EYE_HEIGHT = 0.5       # 眼高（0 = 贴地，1 = 贴顶）
MOVE_SPEED = 4.6       # 最高速度（世界单位 / 秒）
ACCEL = 60.0
FRICTION = 11.0
PLAYER_RADIUS = 0.24

# ---------------- 跳跃 ----------------
# 世界单位里「墙高 = 1.0」，眼高 0.5 就是半墙。跳跃只抬高相机的 z，
# 不改变碰撞（落地判定、被命中判定都不变），所以跳起来躲不掉子弹。
JUMP_SPEED = 2.4        # 起跳初速度（世界单位/秒）：最高点约 0.30，滞空约 0.50s
JUMP_GRAVITY = 9.5      # 重力
AIR_SPRAY = 0.0130      # 滞空时的额外扩散（远大于移动扩散 0.0045，CS 味惩罚）

# ---------------- 武器（AK 手感）----------------
FIRE_INTERVAL = 0.10   # 连发间隔 → 600 RPM
RECOIL_PX = 8.0        # 每发上抬（以 720p 为基准的像素）
RECOIL_YAW_PX = 5.0    # 水平弹道摆幅基准
RECOIL_RECOVER_PX = 60.0
RECOIL_MAX_PX = 200.0
SPRAY_FIRST = 0.0006   # 首发扩散（弧度）
SPRAY_PER_SHOT = 0.0013
SPRAY_MAX = 0.012
SPRAY_RECOVER = 6.0
MOVE_SPRAY = 0.0045    # 移动中的额外扩散
DAMAGE = 100

# ---------------- 靶子 ----------------
BOT_H = 1.05
BOT_W = 0.52
BOT_HEALTH = 100
HEAD_TOP = 0.94        # 头部上沿（占身高的比例）
HEAD_BOT = 0.78
HEAD_HALF_W = 0.11     # 头部半宽（世界单位）
RESPAWN_DELAY = 0.28
MAX_BOTS = 8

# ---------------- 计分 ----------------
SCORE_BODY = 100
SCORE_HEAD = 250
COMBO_STEP = 0.05
COMBO_CAP = 30
COMBO_TIMEOUT = 3.0

# ---------------- 模式参数 ----------------
REFLEX_LIFE = 0.70     # 闪现靶初始存活时间
REFLEX_LIFE_MIN = 0.32 # 满难度时的存活时间
TRACK_TIMEOUT = 0.85   # 跟枪模式多久没命中算断连
PEEK_OUT = 1.15        # 探头停留时长
PEEK_REST = 0.90       # 缩回时长
DIFFICULTY_KILLS = 25  # 每多少次命中升一档难度

# ---------------- 狙击模式（SNIPER，独立第 5 模式）----------------
ADS_ZOOM = 4.0         # 开镜放大倍率（FOV 自动收窄到对应角度）
SNIPER_SENS_MUL = 0.28 # 开镜时鼠标灵敏度乘子（倍率越大越慢，手感更稳）
BOLT_TIME = 0.90       # 栓动上栓延迟（开火后多久才能再开火；0 = 立即单发）
SNIPER_MOVE_MUL = 0.55 # 开镜时移动速度乘子
# 拼接式大地图下能拉出长视线，所以狙击靶距离可以放远
SNIPER_DIST_MIN = 10.0 # 远距小靶最近距离
SNIPER_DIST_MAX = 28.0 # 最远距离（别超过场地对角线，否则永远刷不出来）
SNIPER_BOT_H = 1.05    # 靶高（同 BOT_H）
SNIPER_BOT_W = 0.30    # 靶更窄（远处更难打）
SNIPER_DRIFT = 0.45    # 靶缓慢横向漂移速度（世界单位/秒）

# ---------------- 投掷物：烟雾弹 ----------------
# 烟是"真封视线"的：AI 看不见烟里的你也看不见烟外的你，渲染同理。
# 但子弹照穿（跟 CS 一样），所以封的是信息不是火力。
SMOKE_FUSE = 1.60         # 出手到起烟的引信时间
SMOKE_GROW = 1.40         # 从 0 展开到满半径的时间
SMOKE_RADIUS = 3.20       # 满烟半径（门洞宽 5 格，直径 6.4 足够封死一条路）
SMOKE_HOLD = 16.0         # 满烟维持时间
SMOKE_FADE = 2.50         # 消散时间
SMOKE_THROW_SPEED = 11.0  # 出手水平速度
SMOKE_THROW_UP = 3.20     # 出手上抛速度
SMOKE_GRAVITY = 9.5       # 与跳跃同一套重力
SMOKE_BOUNCE = 0.35       # 落地反弹系数
SMOKE_WALL_BOUNCE = 0.40  # 撞墙反弹系数
SMOKE_FRICTION = 5.0      # 落地滑行摩擦
SMOKE_MAX_ACTIVE = 3      # 场上同时最多几团（超了拒绝出手，先扔的先留）
SMOKE_COOLDOWN = 0.70     # 两次投掷的最小间隔（玩家）
SMOKE_AI_COOLDOWN = 5.0   # AI 两次投掷的最小间隔（避免乱扔）
SMOKE_PRACTICE_MAX = 99   # 练习模式携带量（近乎无限，专心练手感）
# 对战里烟雾弹进经济：不再免费配给，改在买枪阶段花 $150 买，每回合重新购买
SMOKE_PRICE = 150         # 比赛里烟雾弹单价
SMOKE_DIRECT_DMG = 25     # 飞行中直接命中的伤害（落地变烟后不再造成伤害）
SMOKE_HIT_R = 0.45        # 直接命中判定半径（与 Agent 中心的距离阈值）

# ---------------- 颜色（暗色 + 霓虹，极简几何）----------------
C_CEIL_TOP = (18, 25, 41)      # 头顶（近）
C_CEIL_HORIZON = (7, 10, 17)   # 远处（暗）
C_FLOOR_HORIZON = (9, 13, 22)
C_FLOOR_NEAR = (26, 36, 57)
C_GRID = (38, 55, 88)
C_WALL = (46, 58, 88)
C_WALL_SIDE = (31, 40, 63)
C_WALL_ACC = (78, 62, 132)
C_WALL_ACC_SIDE = (53, 42, 92)
# 掩体箱：暖木色，和冷色调的墙拉开区分，一眼能看出"这个能蹲"
C_BOX_LOW = (92, 74, 52)
C_BOX_LOW_SIDE = (64, 51, 36)
C_BOX_TALL = (116, 92, 62)
C_BOX_TALL_SIDE = (80, 63, 43)
C_BOT = (88, 214, 255)
C_BOT_EDGE = (8, 28, 44)
C_BOT_HEAD = (255, 176, 62)
C_BOT_HIT = (255, 255, 255)
C_SHADOW = (4, 7, 13)
C_SMOKE = (198, 206, 220)     # 烟雾弹的烟（偏冷灰白）
C_TRACER = (255, 238, 170)
C_MARK = (255, 255, 255)
C_TEXT = (228, 238, 255)
C_DIM = (108, 128, 164)
C_ACCENT = (110, 226, 255)
C_WARN = (255, 96, 120)
C_GOOD = (140, 255, 190)
C_PANEL = (10, 14, 23)
C_SCOPE = (0, 0, 0)            # 镜外遮罩（黑）
C_SCOPE_RING = (150, 168, 196) # 镜圈
C_SCOPE_LINE = (180, 220, 200) # 镜内十字线 / mil-dot
C_SCOPE_TINT = (18, 26, 22)    # 镜内轻微偏绿（夜视味，可选）

# ================= 3v3 对战（回合制）=================
# 赛制：best of 7 先到 4 胜；每回合一条命，死了观战到回合结束。
MATCH_ROUND_TIME = 90.0       # 每回合交火时长（秒）
MATCH_BUY_TIME = 10.0         # 买枪阶段（可移动，不能开火）
MATCH_END_PAUSE = 2.6         # 回合结算停顿
MATCH_WINS_NEEDED = 4         # 先到 4 个回合胜场
MATCH_MAX_ROUNDS = 7

# 对战专用地图：刻意比练习的小得多（练习是 4×3=12 房间，对战只用 2×2=4 房间）。
# 不然 12 个房间太大，3v3 半天碰不到人。要更紧凑可改 2×1，要稍大改 3×2。
MATCH_TILES_X = 2
MATCH_TILES_Y = 2
MATCH_ROOM_W = 25
MATCH_ROOM_H = 17

PLAYER_HP = 100
AGENT_HP = 100

C_ALLY = (96, 200, 255)        # 队友：蓝
C_ALLY_HEAD = (198, 240, 255)
C_ENEMY = (255, 92, 118)       # 敌人：红
C_ENEMY_HEAD = (255, 190, 120)
C_ALLY_HUD = (120, 210, 255)
C_ENEMY_HUD = (255, 120, 140)

# ---------------- AI 难度：四档预设 + 局内自适应 ----------------
# reaction  看见目标到开第一枪的延迟（秒），越大越呆
# sigma     瞄准误差标准差（度）—— 决定打偏多少，是最主要的手感旋钮
# burst     点射能力 0~1，越高点射越长、连射越稳、误差增长越慢
# strafe    横移躲枪积极性 0~1
# move_mul  移动速度倍率
# ---------------- 蹲（Ctrl）----------------
# 蹲下不改变碰撞体积，但会：下沉相机（眼高降低）、收紧弹道扩散、缩小命中轮廓，
# 所以"蹲点"是真能降低被命中率的（配合掩体柱效果更明显）。
CROUCH_EYE = 0.30          # 蹲下时眼高（站立 0.5）
CROUCH_EYE_DROP = 0.20     # = EYE_HEIGHT - CROUCH_EYE，蹲下时相机下沉量
CROUCH_SPRAY_MUL = 0.45    # 蹲下时扩散乘子（更稳）
CROUCH_H_MUL = 0.62        # 蹲下后命中轮廓高度乘子（更难打中）

# ================= 5v5 积分赛（连续重生 TDM）=================
# 双方各 5 人（你 + 4 AI 队友 vs 5 AI 敌人），无经济、可随时换枪，
# 阵亡后短暂延迟重生并带 3 秒无敌，先累计击杀到 25 的队伍获胜。
SCORE_TEAM_SIZE = 5
SCORE_KILL_TARGET = 25
SCORE_RESPAWN_DELAY = 1.5   # 阵亡到重生的时间（秒）
SCORE_INVULN = 3.0          # 重生后无敌时间（秒）
SCORE_MAP_TILES_X = 3
SCORE_MAP_TILES_Y = 3
SCORE_MAP_ROOM_W = 25
SCORE_MAP_ROOM_H = 17

# ================= 掩体：半高箱 / 高箱（每局随机 · 180° 旋转对称）=================
# 格子类型：0 空地 / 1 墙 / 2 强调柱 / 3 半高箱 / 4 高箱
# 高度用世界单位，1.0 = 一层楼 = 满高墙：
#   半高箱 BOX_LOW_H —— 蹲下（头顶 1.05×0.62≈0.65）完全藏住；站着（1.05）露头可打。
#   高箱   BOX_TALL_H —— 和墙一样全遮蔽，只是配色不同（木箱感）。
# 子弹/视线只要高过箱顶就能飞过去，所以跳起来（z 峰值约 1.1）可以越半高箱 peek。
CELL_LOW_BOX = 3
CELL_TALL_BOX = 4
BOX_LOW_H = 0.70
BOX_TALL_H = 1.0

# 随机生成：每场对战开始（以及每次进练习重开）换一张，成对写入 (x,y) 与其
# 180° 旋转像 (W-1-x, H-1-y)，所以两边地形绝对镜像公平。
COVER_CLUSTERS_PER_ROOM = 2.4   # 每个房间平均放几簇掩体
COVER_MAX_CLUSTERS = 30         # 簇数上限，防止大地图过度堆砌
COVER_TALL_RATIO = 0.35         # 高箱占比，其余是半高箱
COVER_MIN_GAP = 2               # 簇与簇最小间隔（格），避免连成一堵墙
COVER_DOOR_MARGIN = 2           # 门洞周围多少格内不放，保证通行不被堵
COVER_SPAWN_MARGIN = 4          # 出生点周围多少格内不放，开局不被卡
COVER_MAX_TRIES = 400           # 放置尝试上限，放不下就少放几簇

AI_PRESETS = {
    "easy":   dict(reaction=0.55, sigma=6.5, burst=0.35, strafe=0.25, move_mul=0.82),
    "normal": dict(reaction=0.38, sigma=4.0, burst=0.55, strafe=0.50, move_mul=0.94),
    "hard":   dict(reaction=0.25, sigma=2.2, burst=0.75, strafe=0.75, move_mul=1.04),
    "expert": dict(reaction=0.16, sigma=1.2, burst=0.90, strafe=0.95, move_mul=1.15),
}
AI_DIFF_DEFAULT = "normal"
AI_ADAPT_BAND = 0.20      # 自适应只在基准值上下 ±20% 内浮动，不会离谱
AI_ADAPT_RATE = 0.30      # 每回合朝目标调整的幅度（逐回合调，不逐帧，避免抖动）
AI_VIEW_RANGE = 36.0      # 发现敌人的最远距离
AI_PATH_REPLAN = 0.40     # 重算路径的间隔（秒）
AI_STRAFE_PERIOD = 1.10   # 横移换向周期
AI_LOSE_TARGET = 2.20     # 失去视线后还追多久（秒）
AI_MOVE_SPEED = 4.2       # AI 基础移动速度（世界单位/秒）

# 队友（我方 AI）固定用一个"靠谱队友"档，不随敌人难度缩放：
# 比 normal 敌人（sigma 4.0）明显更准，所以玩家手感一般（=实际 2v3）时队友
# 也能扛住 3 个敌人；但比 hard/expert 敌人（sigma 2.2/1.2）略差，所以高难度
# 下队友会吃亏、难度仍由敌人决定，玩家才是主角。改这个数就是调队友强弱。
AI_ALLY_TUNE = dict(reaction=0.32, sigma=3.0, burst=0.66, strafe=0.62, move_mul=1.03)

# ---------------- 经济（只卖枪：无护甲、无投掷物）----------------
ECON_START = 800
ECON_WIN = 3250
ECON_LOSS_BASE = 1400
ECON_LOSS_STEP = 500
ECON_LOSS_MAX = 3400
ECON_MAX = 16000
