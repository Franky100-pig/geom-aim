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

# —— AI 用烟的节制 ——
# 原来只要看见 7~32 格的敌人就 100% 立刻扔，结果开局全员齐扔把地图铺满。
# 现在改成「先过闸 → 再判场景 → 随机延迟 → 概率出手」四步，且推进烟按秒计（不按帧）。
SMOKE_AI_CALM = 6.0       # 交火开始后前 N 秒一律不扔（开局冷静期）
SMOKE_AI_TEAM_MAX = 1     # 同一队伍同时在场的烟团上限（含在飞的）
SMOKE_AI_MIN_DIST = 14.0  # 封视线烟的最小距离，更近就是糊自己的视线，不扔
SMOKE_AI_MAX_DIST = 34.0  # 超过这个距离扔了也没意义
SMOKE_AI_DELAY_MIN = 0.4  # 场景判定通过后，先随机延迟这么久
SMOKE_AI_DELAY_MAX = 1.5
SMOKE_AI_CHANCE = 0.55    # 延迟走完后真正出手的概率
SMOKE_AI_HP_RETREAT = 40  # 血量低于此值且已脱离交火 → 封住追击视线
SMOKE_AI_ADV_RATE = 0.06  # 掩护推进烟：每秒触发概率（乘 dt，与帧率无关）
# 积分赛（5v5）没有经济，AI 不能买烟；这里直接给每波重生发固定颗数，
# 配合上面的节制闸，做到「偶尔扔一颗有章法的烟」而不是一开局铺满。
SMOKE_AI_SCORE_CHARGES = 1

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
# ---------------- 蹲（E）----------------
# 蹲下不改变碰撞体积，但会：下沉相机（眼高降低）、收紧弹道扩散、缩小命中轮廓，
# 所以"蹲点"是真能降低被命中率的（配合掩体柱效果更明显）。
CROUCH_EYE = 0.30          # 蹲下时眼高（站立 0.5）
CROUCH_EYE_DROP = 0.20     # = EYE_HEIGHT - CROUCH_EYE，蹲下时相机下沉量
CROUCH_SPRAY_MUL = 0.45    # 蹲下时扩散乘子（更稳）
CROUCH_H_MUL = 0.62        # 蹲下后命中轮廓高度乘子（更难打中）

# ---------------- 阵亡观战 ----------------
# 阵亡后先向后倒（眼高落到地面、视线逐渐仰起最后对着天空），停留 DEATH_CAM_HOLD
# 秒再切到队友第一视角。观战期间视角完全贴合队友：位置、朝向、俯仰全跟随，
# 鼠标不参与——之前鼠标事件写的是 cam.yaw 基准值，而渲染读的是 eff_yaw，
# 顺序错了导致一动鼠标画面就甩。
DEATH_FALL_TIME = 0.45     # 倒地动画时长（秒）
DEATH_CAM_HOLD = 1.00      # 倒地后停留多久才切到队友视角
DEATH_EYE_H = 0.10         # 倒地后眼高（站立 0.5 / 蹲 0.3）
DEATH_SKY_PITCH_PX = 300.0  # 往后倒最终视线上抬量（720p 基准，≈42% 屏高、接近看天，按 h/720 缩放）
SPEC_SWITCH_TIME = 0.20    # 切换观战目标时，朝向插值过去的时长

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

# ---------------- AI 战术：偷背身（绕后包抄）----------------
# 老行为只有两种：远距离直冲、近距横移。这两条加起来让 AI 有"战术感"：
#   1) 目标把背露给我（朝向背离我）→ 悄悄压上去偷，不原地横移暴露自己；
#   2) 距离合适 + 冷却到了 → 概率绕到目标身后的点包抄，路上保持朝目标可开火。
# 触发概率按难度缩放（用 burst 当"水平"代理），easy 基本不绕、expert 常常绕。
AI_FLANK_ENABLED = True    # 关掉就退回老行为（直冲 + 横移）
AI_FLANK_CHANCE_MIN = 0.12  # 最低难度每次冷却结束的触发概率
AI_FLANK_CHANCE_MAX = 0.75  # 最高难度每次冷却结束的触发概率
AI_FLANK_BACK_BONUS = 1.8   # 目标背身时概率乘这个系数（背身更值得绕/偷）
AI_FLANK_CD = 5.0          # 两次包抄之间的冷却（秒）
AI_FLANK_RADIUS = 5.5      # 包抄点离目标多远（绕到身后这个半径的圈上）
AI_FLANK_MAX_T = 4.5       # 包抄最长持续，超时回到正面对枪
AI_FLANK_HP_MIN = 35.0     # 血量低于此值不包抄（保命优先）
AI_FLANK_MIN_DIST = 4.5    # 比这还近就别绕了，直接对枪
AI_FLANK_MAX_DIST = 22.0   # 比这还远绕过去没意义
AI_FLANK_BACK_DOT = -0.15  # 目标朝向 ·(目标→我) 小于该值 = 背身暴露
AI_FLANK_PUSH_MUL = 1.25   # 背身偷袭时的接近速度倍率（压得更快）

# ---------------- 地形上下起伏（高度图）----------------
# 给地图叠一层平滑的高度场：玩家相机随地形升降（真·上下起伏），
# 视线会被山脊挡住、洼地能藏人；渲染上地面网格与墙脚跟着地形走。
# 关闭（TERRAIN_ENABLED=False）或幅度为 0 时，所有地图退回完全平整，
# 行为与旧版本逐像素一致（h_at 恒返回 0，不引入任何遮挡）。
TERRAIN_ENABLED = True     # 主开关
TERRAIN_AMP = 0.55         # 起伏幅度（世界单位，墙高=1.0；0.55 是克制的缓坡）
TERRAIN_FREQ = 0.16        # 起伏频率：越小山头越大越平缓
TERRAIN_SEED = 1337        # 高度场种子（与对战/练习地图共用同一份，保证两边公平）

# ---------------- 经济（只卖枪：无护甲、无投掷物）----------------
ECON_START = 800
ECON_WIN = 3250
ECON_LOSS_BASE = 1400
ECON_LOSS_STEP = 500
ECON_LOSS_MAX = 3400
ECON_MAX = 16000

# ---------------- 局域网联机 ----------------
NET_PORT = 8765            # 主机 UDP 监听端口
NET_TICK_HZ = 30          # 主机广播快照频率
NET_INPUT_HZ = 60         # 客户端上行输入频率
NET_TIMEOUT = 4.0         # 多少秒没收到某客户端输入就踢掉
NET_MAX_HUMANS = 3        # 一个房间最多真人数量（含主机）
ROOM_TEAM_SIZE = 5        # 每队人数（空位由 AI 补）
HUMAN_MOVE_SPEED = 4.2    # 真人移动速度（与 AI 一致）
HUMAN_JUMP_V = 5.2        # 真人跳跃初速度（世界单位/秒）
HUMAN_GRAVITY = 16.0      # 真人重力（用于跳跃下落）
