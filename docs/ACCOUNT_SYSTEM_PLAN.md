# GEOM AIM 账号系统预案（未实施）

> **状态：预案。** 本文档不表示任何排期承诺。触发条件满足前不动工。
> 参考蓝本：`Franky100-pig/Resona` fork main 分支（已修复安全漏洞的版本）。

---

## 1. 触发条件

**当用户数 ≥ 20 时启动本方案。**

用户数怎么数（按成本从低到高）：

| 阶段 | 度量方式 | 成本 |
|------|---------|------|
| 现在 | GitHub Release 资产下载量（`gh api repos/Franky100-pig/geom-aim/releases` 统计，粗略去掉自己） | 零 |
| 有服务器后 | 游戏首启动时可选的匿名 ping（只传 UUID + 版本号，可关闭） | ~20 行 |

原则：**没有可信的用户数之前，不做账号系统。** 为 5 个用户维护服务器是负收益。

## 2. 范围

### 只做（~150 行后端 + 客户端对接）
- 注册 / 登录 → 拿 token
- token 鉴权的成绩上报端点（为排行榜准备）
- 登出
- 历史对局记录查询端点（跨设备同步本地战绩，见 §7）

### 明确不做（写死在方案里，防止范围蔓延）

| 不做 | 理由 |
|------|------|
| 邮箱验证 | 没有邮件服务器，注册零摩擦 |
| 找回密码 | 忘密码 = 重新注册（游戏可接受）。**禁止**用安全问题代替 |
| CAPTCHA | 见 §4，当前威胁模型下不必要 |
| SSO / 第三方登录 | 用户量小，维护 OAuth 对接不划算 |
| 多人匹配服务器 | 账号 ≠ 联机。真人对战是另一个独立项目 |
| 用户资料/头像 | 无社交功能就不需要 |

## 3. 技术方案

```
后端:  FastAPI（或 Flask）单文件 ~150 行
数据库: SQLite，两张表
鉴权:  opaque random token（存哈希进库），Authorization 头携带
部署:  一台便宜 VPS + Caddy（自动 HTTPS）
```

### 数据库 Schema

```sql
CREATE TABLE users (
    id            INTEGER PRIMARY KEY,
    username      TEXT UNIQUE NOT NULL COLLATE NOCASE,
    password_hash TEXT NOT NULL,          -- werkzeug pbkdf2:sha256:600000
    token_version INTEGER NOT NULL DEFAULT 0,  -- +1 = 全设备下线
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE tokens (
    token_hash  TEXT PRIMARY KEY,         -- sha256(token)，库内永不存明文
    user_id     INTEGER NOT NULL REFERENCES users(id),
    token_version INTEGER NOT NULL,       -- 校验时必须等于 users 表当前值
    expires_at  TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE matches (
    id           INTEGER PRIMARY KEY,
    user_id      INTEGER NOT NULL REFERENCES users(id),
    client_uuid  TEXT NOT NULL,           -- 客户端生成，用于幂等去重
    mode         TEXT NOT NULL,           -- aim_botz / reflex / tracking / peek / bo7
    weapon       TEXT,                    -- 主武器（可空）
    score        INTEGER,
    accuracy     REAL,                    -- 0.0~1.0
    kills        INTEGER,
    time_sec     INTEGER,                 -- 本局时长
    result       TEXT,                    -- win / loss / n/a
    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (user_id, client_uuid)         -- 防重复上传污染历史
);
```

### API 草图

| 端点 | 说明 | 防护 |
|------|------|------|
| `POST /api/register` | username + password | 每IP限流 + honeypot 字段 |
| `POST /api/login` | username + password → token | 每IP + 每用户名 双维限流 |
| `POST /api/logout` | 作废当前 token | 需鉴权 |
| `GET /api/me` | 验活 | 需鉴权 |
| `POST /api/scores` | 上报成绩（排行榜用） | 需鉴权 + 合理性校验（§4） |
| `POST /api/matches/batch` | 批量上传本地战绩（跨设备同步） | 需鉴权 + `user_id` 服务端取 + `client_uuid` 幂等 |
| `GET /api/history` | 查询当前用户历史对局（分页） | 需鉴权 + 只返回自己行 + 分页上限 |

### 安全清单（从 Resona 审计中继承的纪律）

1. 密码只存 PBKDF2 哈希，迭代 ≥ 60 万
2. **恒时校验**：账号不存在也对假哈希跑完整 PBKDF2；存在/不存在返回同一句错误
3. 登录与注册限流：每 IP + 每用户名
4. 改密码 → `token_version + 1` → 所有旧 token 立即失效
5. token 只存 SHA-256 哈希，带过期时间，定期清理
6. 全站 HTTPS（Caddy 自动证书）
7. 错误响应不区分「用户不存在」和「密码错误」

## 4. 人机验证决策：初始不做 CAPTCHA

**结论：不引入。** 理由：

1. **威胁模型不成立。** bot 注册盯的是有价值的目标（免费额度、邮箱信誉、SEO 垃圾）。一个无邮箱、无支付、无 UGC 的游戏账号，伪造它没有任何收益。
2. **CAPTCHA 防不了真正的风险。** 如果上排行榜，真实威胁是**刷分**——而刷分者会先正常通过一次验证，然后永远合法地提交假成绩。防刷分靠的是**服务端合理性校验**（单局分数上限、用时/击杀比物理约束、单位时间提交频率），不是注册时的人机验证。
3. **代价不对称。** 受益（≈0） vs 成本（20 个真人用户的注册摩擦 + 集成维护）。

### 升级路径（观察到 bot 再走，不预先建设）

```
第 0 级（默认）：限流 + honeypot 隐藏字段（对脚本零抵抗成本，对真人零感知）
第 1 级：PoW 验证码（capjs，Resona 同款，自托管无隐私争议）
第 2 级：Cloudflare Turnstile（有 CF 账号后最省事的方案）
```

触发信号：注册日志出现同 IP 批量注册、随机字符串用户名、注册后无任何游戏行为。

## 5. 客户端对接

| 形态 | 做法 |
|------|------|
| pygame 版 | `net.py` 扩展：登录成功后 token 存本地文件（`os.chmod 600`），请求带 `Authorization` 头 |
| UE5 版 | HTTP 模块（或 VaRest）调 REST；token 不落盘，放内存，重启重登 |

客户端永远不接触密码哈希以外的东西；所有校验在服务端。

## 6. 工作量估计

| 部分 | 时间 |
|------|------|
| 后端（复用 Resona 模式） | ~1 天 |
| pygame 客户端对接 + UI | ~0.5 天 |
| UE5 客户端对接 | ~1 天 |
| 部署 + 域名 + HTTPS | ~0.5 天 |

## 7. 历史对局记录查询（Match History）

### 现状与动机

`9976de8` 已实现 **Phase 1：本地战绩层 + 历史面板**（`stats.py` 离线 SQLite，游戏内可查看历史），离线优先、无需登录。账号系统激活后的额外价值只有一件事：**跨设备同步**——同一账号在不同 Mac 上能看到同一份战绩。因此本方案不重做本地历史，而是让本地战绩「可上云」。

### 设计原则

1. **本地仍是真源。** 离线照样能玩、能记录、能看历史。账号只是「同步通道」，不是记录的前提。
2. **同步可选、可关。** 未登录或关闭同步时，行为完全退回 Phase 1。
3. **幂等上传。** 每条本地战绩在生成时带一个 `client_uuid`，重复上传不会污染历史。

### 数据模型（新增 `matches` 表，见 §3）

字段对齐 `stats.py` 现有记录：模式、武器、分数、命中率、击杀、时长、胜负。
`UNIQUE (user_id, client_uuid)` 保证同一条本地战绩无论上传几次都只落一行。

### 端点（见 §3 API 草图）

| 端点 | 作用 |
|------|------|
| `POST /api/matches/batch` | 客户端把本地未同步战绩批量上传；服务端按 `(user_id, client_uuid)` upsert |
| `GET /api/history?limit=&offset=&mode=` | 返回当前用户战绩，分页，仅自己行 |

### 与现有 `stats.py` 的衔接

- 本地 SQLite 增一列 `synced INTEGER DEFAULT 0`；每局结束若处于登录态，尝试 `POST /api/matches/batch`，成功后标 `synced=1`。
- `GET /api/history` 仅用于「换设备后查看 / 网页端查看」，**不回写覆盖本地**——本地永远是最完整的离线真源。
- 历史面板增加「从服务器刷新」按钮（登录态可用），不登录则隐藏。

### 安全与隐私

1. `user_id` 一律从鉴权 token 取，**绝不从请求体读**，杜绝越权读他人战绩。
2. `GET /api/history` 强制 `WHERE user_id = ?`，分页上限（如 `limit<=100`）防拉取滥用。
3. 历史默认私有；公开历史（排行榜页）是另一个独立决策，不在此范围内。

### 客户端对接（扩展 §5）

| 形态 | 做法 |
|------|------|
| pygame 版 | `stats.py` 在登录态每局结束尝试上传；`history` 面板加「从服务器刷新」 |
| UE5 版 | 战绩结构体带 `client_uuid`，同样走 batch 上传；内存态，不落盘 token |

### 工作量估计（追加到 §6）

| 部分 | 时间 |
|------|------|
| 后端 `matches` 表 + 2 端点（复用 Resona 模式） | ~0.5 天 |
| pygame `stats.py` 同步标记 + 上传 + 刷新 UI | ~0.5 天 |

## 8. 决策记录

- **2026-09-28**：用户量小（<20），暂不实施；确立触发条件与本预案。
- 核心取舍：账号系统的价值（跨设备成绩同步） < 维护成本，直到有真实用户基数。
- CAPTCHA 决策：初始不做，理由见 §4；升级路径已定义，按观察触发而非预先建设。
