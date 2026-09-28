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
```

### API 草图

| 端点 | 说明 | 防护 |
|------|------|------|
| `POST /api/register` | username + password | 每IP限流 + honeypot 字段 |
| `POST /api/login` | username + password → token | 每IP + 每用户名 双维限流 |
| `POST /api/logout` | 作废当前 token | 需鉴权 |
| `GET /api/me` | 验活 | 需鉴权 |
| `POST /api/scores` | 上报成绩（排行榜用） | 需鉴权 + 合理性校验（§4） |

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

## 7. 决策记录

- **2026-09-28**：用户量小（<20），暂不实施；确立触发条件与本预案。
- 核心取舍：账号系统的价值（跨设备成绩同步） < 维护成本，直到有真实用户基数。
- CAPTCHA 决策：初始不做，理由见 §4；升级路径已定义，按观察触发而非预先建设。
