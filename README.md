# 迅维网签到（chinafix-sign）

> chinafix 迅维网 每日自动签到。云端 GitHub Actions 跑，本机不用开机。

**仓库名说明**：GitHub 不支持中文仓库名（会被静默丢弃），所以仓库名是英文
`chinafix-sign`。中文别名记在仓库描述里：**【迅维网签到】**。

---

## 这个仓库是干什么的

每天自动登录迅维网完成签到，保持账号活跃度。

| 项目 | 说明 |
|---|---|
| 平台 | 迅维网（chinafix） |
| 运行方式 | GitHub Actions 每天自动，约北京 01:30 |
| 本机要求 | 无。不用开机、不用开客户端 |
| 失败通知 | 推企业微信（只推失败） |

---

## 重要说明

- **仓库 2026-11-24 ~ 11-30 临时公开**（Actions 免费额度按私有仓库计分钟，本月已耗尽；公开仓库不计费），12-01 改回 Private。Cookie 只在 Secrets，代码与历史里没有。
- **账号信息不进代码**。全部在 `Settings → Secrets and variables → Actions`。
- **日志脱敏**。Cookie / 令牌只留前缀，不落完整值。
- 公开期间请勿 fork 到别处；12-01 会改回 Private。

---

## 运行时间

| 北京时刻 | 动作 |
|---|---|
| 约 01:30 | 云端自动签到 |

GitHub 定时任务会随机延迟（实测 5~6 小时），实际执行常落在
01:30 ~ 07:00，属正常现象，不影响签到结果。

---

## 心跳监测

已纳入「自动心跳监测」，Healthchecks 里的名字是 `签到-迅维网`。

| 状态 | 含义 |
|---|---|
| `up` | 正常 |
| `grace` | 等今天这一跑，宽限期内，**不是故障** |
| `down` | 真没跑，去 Actions 补签 |

---

## 目录

```
.github/workflows/sign.yml    云端定时任务（含心跳上报）
chinafix_sign.py              签到逻辑
requirements.txt              Python 依赖
```

---

## 排错

| 现象 | 原因 | 怎么办 |
|---|---|---|
| Actions 红叉 | 账号凭据失效 | 重新登录后更新 Secret |
| 提示需要验证码 | 触发风控 | 停一天，或换网络手动登录一次 |
| 心跳 down | 当天没跑 | Actions → Run workflow 补签 |

---

## 安全

- 凭据仅存 GitHub Secrets（加密）
- 仓库临时公开至 12-01，凭据只在 Secrets
- 停用：删对应 Secret，或 Disable workflow

---

## 相关仓库

| 仓库 | 中文名 |
|---|---|
| `workbuddy-checkin-public` | WorkBuddy 签到 |
| `raccoon-checkin` | 小浣熊签到 |
| `qoder-checkin` | Qoder 签到 |
| `Cloud189Checkin` | 天翼云盘签到 |
| `hyperdown-checkin` | Hyperdown 签到 |
| `checkin-watchdog` | 心跳告警中转 |

---

## 许可

个人自用，不对外分发。
