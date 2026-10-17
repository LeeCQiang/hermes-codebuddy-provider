# Hermes × CodeBuddy 通道

**把 CodeBuddy（腾讯）的订阅额度，接成 Hermes Agent 里的一个 OpenAI 兼容模型通道。**

[English](README.md) · MIT License

---

> **非官方项目**：与腾讯官方无关，未获授权或背书。这里记录的协议是观察官方 IDE 客户端流量还原出来的。请只用自己的账号、仅作个人用途、并遵守服务方条款。详见[免责声明](#免责声明)。

---

## 为什么需要它

Hermes 支持任意 OpenAI 兼容端点，但 CodeBuddy 有四个地方不能直接填个 key 就用：

| 障碍 | 实际表现 |
|---|---|
| 认证 | 不是固定 API key，而是 `access_token` + `refresh_token`，要经浏览器登录换取 |
| 流式 | **只支持流式**。非流式直接 `400 code 11101` |
| 身份头 | 必须带 `X-Domain` / `X-Product` / `X-IDE-*`，缺了就当未授权 |
| 思考型模型 | 部分模型默认先思考，`max_tokens` 给小了会返回空 `content` |

把这四点处理掉之后，它就是一个普通的 OpenAI 风格端点：流式、工具调用、30+ 模型。

## 特性

- ✅ 流式对话 + **工具/函数调用**（已在 Hermes 内跑通端到端）
- ✅ 一份凭据 **30+ 模型**（GLM、DeepSeek、混元、Kimi、MiniMax、Step…）
- ✅ **自动续期**（access_token 约 28 天，滚动续）
- ✅ 借 Hermes 原生 `fallback_providers` 实现**故障自动回切**
- ✅ **探活守护**：失败先续期、连续失败告警、必要时自动把主力切回去
- ✅ Python 纯标准库，无第三方依赖

## 工作原理

```
         ┌──────────┐  1. POST /v2/plugin/auth/state?platform=ide
         │  浏览器   │ ────────────────────────────────────────────┐
         │  (你)     │      ← authUrl + state                     │
         └────┬─────┘                                            │
              │ 2. 打开链接登录                                   ▼
              ▼                                            ┌──────────┐
         ┌──────────┐  3. GET /v2/plugin/auth/token?state=… │ 辅助脚本  │
         │ CodeBuddy│ ◀───────────────────────────────────  │ (本地)    │
         │ 登录页    │      → accessToken / refreshToken     └────┬─────┘
         └──────────┘                                           │ 写入
                                                                ▼
                                          ~/.hermes/codebuddy/credentials.json (0600)
                                                                │ 同步
                                                                ▼
                                                        ~/.hermes/.env
                                                                │
                                                                ▼
                                 Hermes provider `codebuddy` → /v2/chat/completions
```

### 端点

Base：`https://copilot.tencent.com`

| 方法 | 路径 | 用途 |
|---|---|---|
| `POST` | `/v2/plugin/auth/state?platform=ide` | 创建登录会话，返回 `authUrl` + `state` |
| `GET` | `/v2/plugin/auth/token?state=<state>` | 轮询取令牌（用户登录完成后） |
| `POST` | `/v2/plugin/auth/token/refresh` | 用 `refresh_token` 换新 `access_token` |
| `GET` | `/console/enterprises/personal/models` | 账号可用模型及元数据 |
| `POST` | `/v2/chat/completions` | 对话补全（OpenAI 形状，仅 SSE） |

### 对话必备请求头

```http
Authorization: Bearer <access_token>
X-Domain: <令牌响应里的 domain>        # 例如 www.codebuddy.cn，不是 API 主机名
X-Product: CodeBuddy
X-Product-Code: codebuddy
X-Agent-Purpose: conversation
X-IDE-Name: CodeBuddy
X-IDE-Type: CodeBuddy
X-IDE-Version: 1.106.1
User-Agent: CodeBuddyIDE/1.106.1
Accept: text/event-stream
Content-Type: application/json
```

续期请求额外需要 `X-Refresh-Token: <refresh_token>` 和 `X-Auth-Refresh-Source: ide-main`。

> ⚠️ `X-Domain` **不是** `copilot.tencent.com`，必须用令牌响应里给的值；填错只会得到 `401`。

## 环境要求

- Hermes Agent（支持自定义 provider 与 `fallback_providers` 的版本）
- Python 3.8+（脚本只用标准库）
- 一个有额度/订阅的 CodeBuddy 账号

## 快速开始

### 1. 拿凭据

```bash
mkdir -p ~/.hermes/codebuddy
cp scripts/codebuddy_login.py ~/.hermes/codebuddy/
python3 ~/.hermes/codebuddy/codebuddy_login.py login
```

脚本会打印一个登录链接。浏览器打开、登录，脚本自动落盘：

```json
{
  "access_token": "…",
  "refresh_token": "…",
  "domain": "www.codebuddy.cn",
  "expires_in": 2419200,
  "refresh_expires_in": 2592000,
  "obtained_at": 1760000000
}
```

并把 `CODEBUDDY_ACCESS_TOKEN=…` 写进 `~/.hermes/.env`（权限 `0600`）。

### 2. 注册 provider

```bash
hermes config set providers.codebuddy.api https://copilot.tencent.com/v2
hermes config set providers.codebuddy.name CodeBuddy
hermes config set providers.codebuddy.key_env CODEBUDDY_ACCESS_TOKEN
hermes config set providers.codebuddy.context_length 300000
hermes config set providers.codebuddy.extra_headers '{"X-Domain":"www.codebuddy.cn","X-Product":"CodeBuddy","X-Product-Code":"codebuddy","X-Agent-Purpose":"conversation","X-IDE-Name":"CodeBuddy","X-IDE-Type":"CodeBuddy","X-IDE-Version":"1.106.1","User-Agent":"CodeBuddyIDE/1.106.1"}'
```

等价的 YAML：

```yaml
providers:
  codebuddy:
    api: https://copilot.tencent.com/v2
    name: CodeBuddy
    key_env: CODEBUDDY_ACCESS_TOKEN
    context_length: 300000
    extra_headers:
      X-Domain: www.codebuddy.cn
      X-Product: CodeBuddy
      X-Product-Code: codebuddy
      X-Agent-Purpose: conversation
      X-IDE-Name: CodeBuddy
      X-IDE-Type: CodeBuddy
      X-IDE-Version: 1.106.1
      User-Agent: CodeBuddyIDE/1.106.1
```

### 3. 切换模型

```bash
hermes config set model.provider codebuddy
hermes config set model.default glm-5.3-flash
hermes gateway restart        # 运行中的进程不会热加载配置
```

### 4. 留好安全网

```bash
hermes config set fallback_providers '[{"provider":"deepseek","model":"deepseek-chat"}]'
```

请求遇到鉴权失败、限流或 5xx 时，Hermes 会原地换 provider 重试，通道挂了不会把会话搞断。

### 5. 验证

```bash
python3 ~/.hermes/codebuddy/check.py           # → OK alive: …
hermes chat -q "执行 echo HELLO" --yolo        # 工具调用冒烟测试
```

## 配置项说明

| 键 | 含义 | 备注 |
|---|---|---|
| `api` | Base URL | `https://copilot.tencent.com/v2`（SDK 会自己拼 `/chat/completions`） |
| `key_env` | 存放令牌的环境变量 | 避免把密钥写进 `config.yaml` |
| `context_length` | Hermes 认为的上下文长度 | 模型端最高 1M，300000 是稳妥默认 |
| `extra_headers` | 身份头 | 必须与令牌里的 domain 一致 |

## 模型清单（实测）

个人账号 `GET /console/enterprises/personal/models` 返回（节选）：

| 模型 | 备注 |
|---|---|
| `glm-5.3`、`glm-5.3-flash` | 快（首字约 1s） |
| `glm-5.2 / 5.1 / 5.0 / 4.7 / 4.6 / 4.6v`、`glm-5v-turbo` | GLM 系列 |
| `deepseek-v4.1-flash`、`deepseek-v4-pro`、`deepseek-v4-flash`、`deepseek-v3-2-volc` | DeepSeek 系列 |
| `kimi-k3-1`、`kimi-k2.8-preview`、`kimi-k2.7`、`kimi-k2.6`、`kimi-k2.5`、`kimi-k2-thinking` | Kimi 系列 |
| `hunyuan-2.0-thinking`、`hunyuan-chat` | 混元 |
| `minimax-m3`、`minimax-m2.5`、`step-5-preview`、`hy3`、`hy3-x`、`hy4-preview` | 其它 |
| `auto` | 服务端路由（会多一层延迟） |

模型元数据里带 `defaultLength` / `maxInputTokens` / `maxOutputTokens` / 计费倍率，部分条目 `onlyReasoning: true` 表示"必先思考"。

> 清单随时可能变，用接口查，别硬编码。

## 令牌生命周期

| 令牌 | 实测有效期 |
|---|---|
| `access_token` | 约 28 天 |
| `refresh_token` | 约 30 天，滚动更新 |

`codebuddy_login.py refresh` 会换新并重写 `.env`。每周跑一次就长期在线；refresh 也过期时重新走 `login`。

## 探活与自动回切

`scripts/codebuddy_guard.sh` 专为 Hermes cron 的 `no_agent` 模式设计 —— **正常时零输出，异常才说话**：

1. 用一次 64 token 的真实流式对话探活
2. 失败 → 先续期 → 再探一次
3. 连续失败（默认 2 次）→ 输出告警；若主力是 `codebuddy`，把配置切回 `FALLBACK_PROVIDER`/`FALLBACK_MODEL`
4. access_token 剩余 < 7 天 → 静默续期

```bash
cp scripts/check.py scripts/codebuddy_login.py scripts/codebuddy_guard.sh ~/.hermes/codebuddy/
chmod 700 ~/.hermes/codebuddy/*.py ~/.hermes/codebuddy/*.sh
# Hermes cron 的 script 必须放在 ~/.hermes/scripts/ 下
ln -sf ~/.hermes/codebuddy/codebuddy_guard.sh ~/.hermes/scripts/codebuddy_guard.sh
```

然后建 cron（`no_agent: true`，`0 10 * * *`，script `codebuddy_guard.sh`，投递到你的会话）。

## 排错

| 现象 | 原因 | 处理 |
|---|---|---|
| `400` `code 11101` "Non-stream chat request is currently not supported" | 发了 `stream: false` | 必须流式；需要非流式的辅助任务请走别的 provider |
| 每个请求都 `401` | `X-Domain` 错/缺，或 token 过期 | 用令牌响应里的 `domain`；续期 |
| `403` `code 11140` | 账号风控拦截 | 别再重试；这是账号级的，代码改不了 |
| `content` 为空、只有 `reasoning_content` | 思考把预算烧光了 | 调大 `max_tokens`（探活 ≥64，正经用要更大） |
| 工具调用参数残缺 | 同上，流被截断 | 调大 `max_tokens` |
| 改了配置没反应 | 运行中的进程缓存了 provider | `hermes gateway restart`（或会话内 `/model`） |
| 国内 TLS 报错/超时 | 上游抖动 | 重试，或走你自己的代理 |

## 安全与隐私

- 凭据在 `~/.hermes/codebuddy/credentials.json`（`0600`）和 `.env`（`0600`），**不写进** `config.yaml`，**不提交**到仓库。
- 本仓库不含任何账号标识、令牌、主机名或 IP；你自己的信息只填在本地 `config.yaml` 里。
- 一个账号一个用户。**不要做账号池、积分农场、多账号轮换** —— 违反条款，封的是你自己的号。
- token 是 bearer 凭据，谁拿到谁就能花你的额度。

## 常见问题

**国际版 WorkBuddy 能用吗？**
协议形状类似，但主机、`platform` 参数和 User-Agent 不同。本仓库针对国内 `copilot.tencent.com`（`platform=ide`）。

**Hermes 的辅助任务（标题、摘要）能用吗？**
只要它们是流式的才行。CodeBuddy 拒绝非流式，所以辅助模型建议指向别的 provider。

**为什么不直接用官方 API key？**
有 key 就直接用。这个项目的存在是为只有 IDE 登录入口的订阅/额度账号。

**稳定吗？**
这是未公开协议，端点和请求头随时可能变。所以才有探活守护。

## 免责声明

非官方、社区自建集成，与腾讯、CodeBuddy、Nous Research 均无关联。你需要自行遵守服务条款与当地法规。作者不提供任何担保，也不对账号受限、数据丢失或额度消耗承担责任。风险自负。

## License

[MIT](LICENSE)
