# Hermes × CodeBuddy Provider

**Use a CodeBuddy (Tencent) subscription as an OpenAI-compatible model channel inside [Hermes Agent](https://github.com/NousResearch/hermes-agent).**

[中文说明](README.zh-CN.md) · MIT License

---

> **Unofficial.** This project is not affiliated with, endorsed by, or supported by Tencent. It documents a client protocol that the official IDE/CLI already uses, reconstructed by observing traffic. Use it with **your own** account, for personal use, and in line with the provider's Terms of Service. See [Disclaimer](#disclaimer).

---

## Why this exists

Hermes talks to any OpenAI-compatible endpoint, but CodeBuddy is not a plain drop-in:

| Obstacle | What actually happens |
|---|---|
| Auth | Not an API key — a short-lived `access_token` plus a `refresh_token`, obtained through a browser login flow |
| Streaming | **Streaming only.** Non-stream requests are rejected with `400 code 11101` |
| Identity headers | Requests must carry `X-Domain` / `X-Product` / `X-IDE-*` headers, or they are treated as unauthorized |
| Reasoning models | Some models always "think" first; a small `max_tokens` returns an empty `content` |

Once those four are handled, you get a normal OpenAI-shaped endpoint with streaming, tool calls, and 30+ models behind it.

## Features

- ✅ Streaming chat completions with **tool/function calling** (verified end-to-end inside Hermes)
- ✅ **30+ models** (GLM, DeepSeek, Hunyuan, Kimi, MiniMax, Step…) on one credential
- ✅ Automatic **token refresh** (~28-day access tokens, rolling renewal)
- ✅ **Failover** to any other provider through Hermes' native `fallback_providers`
- ✅ **Health monitoring** with a cron guard that refreshes, alerts, and rolls the config back
- ✅ Zero third-party Python dependencies (stdlib only)

## How it works

```
        ┌────────────┐   1. POST /v2/plugin/auth/state?platform=ide
        │  you       │ ─────────────────────────────────────────────┐
        │  (browser) │      ← authUrl + state                      │
        └─────┬──────┘                                             │
              │ 2. open URL, sign in                              │
              ▼                                                   ▼
        ┌────────────┐   3. GET /v2/plugin/auth/token?state=…   ┌─────────┐
        │  CodeBuddy │ ◀──────────────────────────────────────  │ helper  │
        │  login page│      → accessToken / refreshToken        │ script  │
        └────────────┘                                          └────┬────┘
                                                                     │ writes
                                                                     ▼
                                                     ~/.hermes/codebuddy/credentials.json (0600)
                                                                     │
                                                                     │ mirrors token
                                                                     ▼
                                                              ~/.hermes/.env
                                                                     │
                                                                     ▼
                                            Hermes provider `codebuddy` → /v2/chat/completions
```

### Endpoints

Base URL: `https://copilot.tencent.com`

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/v2/plugin/auth/state?platform=ide` | Create a login session, returns `authUrl` + `state` |
| `GET` | `/v2/plugin/auth/token?state=<state>` | Poll until the user finishes login, returns the token pair |
| `POST` | `/v2/plugin/auth/token/refresh` | Exchange `refresh_token` for a new `access_token` |
| `GET` | `/console/enterprises/personal/models` | List models available to the account, with metadata |
| `POST` | `/v2/chat/completions` | Chat completions (OpenAI-shaped, SSE only) |

### Required headers (chat)

```http
Authorization: Bearer <access_token>
X-Domain: <domain from the token response>       # e.g. www.codebuddy.cn — NOT the API host
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

The refresh call additionally needs `X-Refresh-Token: <refresh_token>` and `X-Auth-Refresh-Source: ide-main`.

> `X-Domain` is **not** `copilot.tencent.com`. Take it from the token response — sending the wrong domain yields a plain `401`.

## Requirements

- Hermes Agent (any recent version with custom providers + `fallback_providers`)
- Python 3.8+ (helper scripts use only the standard library)
- A CodeBuddy account with an active subscription/credits

## Quick start

### 1. Get credentials

```bash
mkdir -p ~/.hermes/codebuddy
cp scripts/codebuddy_login.py ~/.hermes/codebuddy/
python3 ~/.hermes/codebuddy/codebuddy_login.py login
```

It prints a URL. Open it, sign in, and the script stores:

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

and writes `CODEBUDDY_ACCESS_TOKEN=…` into `~/.hermes/.env` (mode `0600`).

### 2. Register the provider

```bash
hermes config set providers.codebuddy.api https://copilot.tencent.com/v2
hermes config set providers.codebuddy.name CodeBuddy
hermes config set providers.codebuddy.key_env CODEBUDDY_ACCESS_TOKEN
hermes config set providers.codebuddy.context_length 300000
hermes config set providers.codebuddy.extra_headers '{"X-Domain":"www.codebuddy.cn","X-Product":"CodeBuddy","X-Product-Code":"codebuddy","X-Agent-Purpose":"conversation","X-IDE-Name":"CodeBuddy","X-IDE-Type":"CodeBuddy","X-IDE-Version":"1.106.1","User-Agent":"CodeBuddyIDE/1.106.1"}'
```

Equivalent YAML:

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

### 3. Switch the model

```bash
hermes config set model.provider codebuddy
hermes config set model.default glm-5.3-flash
hermes gateway restart        # running sessions do not hot-reload config
```

### 4. Keep a safety net

```bash
hermes config set fallback_providers '[{"provider":"deepseek","model":"deepseek-chat"}]'
```

Hermes switches provider in place when a request fails with auth/rate-limit/5xx errors, so a dead CodeBuddy channel degrades instead of breaking the conversation.

### 5. Verify

```bash
python3 ~/.hermes/codebuddy/check.py           # → OK alive: …
hermes chat -q "run: echo HELLO" --yolo        # tool-calling smoke test
```

## Configuration reference

| Key | Meaning | Notes |
|---|---|---|
| `api` | Base URL | `https://copilot.tencent.com/v2` (the SDK appends `/chat/completions`) |
| `key_env` | Env var holding the token | Keeps secrets out of `config.yaml` |
| `context_length` | Context window Hermes assumes | Models expose up to 1M; 300000 is a safe default |
| `extra_headers` | Identity headers | Must match the token's domain |

## Model catalog (observed)

`GET /console/enterprises/personal/models` on a personal account returned, among others:

| Model | Notes |
|---|---|
| `glm-5.3`, `glm-5.3-flash` | Fast (~1s first token) |
| `glm-5.2 / 5.1 / 5.0 / 4.7 / 4.6 / 4.6v`, `glm-5v-turbo` | GLM family |
| `deepseek-v4.1-flash`, `deepseek-v4-pro`, `deepseek-v4-flash`, `deepseek-v3-2-volc` | DeepSeek family |
| `kimi-k3-1`, `kimi-k2.8-preview`, `kimi-k2.7`, `kimi-k2.6`, `kimi-k2.5`, `kimi-k2-thinking` | Kimi family |
| `hunyuan-2.0-thinking`, `hunyuan-chat` | Tencent Hunyuan |
| `minimax-m3`, `minimax-m2.5`, `step-5-preview`, `hy3`, `hy3-x`, `hy4-preview` | Others |
| `auto` | Server-side routing (adds latency) |

Model metadata includes `defaultLength` / `maxInputTokens` / `maxOutputTokens` / credit multipliers, and some entries flag `onlyReasoning: true` — those always think before answering.

> Catalogs change without notice. Query the endpoint rather than hard-coding the list.

## Token lifecycle

| Token | Lifetime (observed) |
|---|---|
| `access_token` | ~28 days |
| `refresh_token` | ~30 days, rolling |

`codebuddy_login.py refresh` rotates the pair and rewrites `.env`. Run it weekly and you never touch the login flow again; if the refresh token itself expires, re-run `login`.

## Monitoring & automatic rollback

`scripts/codebuddy_guard.sh` is built for Hermes cron `no_agent` mode — **silent when healthy**, loud when not:

1. Probe with a real 64-token streaming chat.
2. On failure, refresh the token and probe again.
3. On repeated failure (default 2 runs), print an alert; if `codebuddy` is the active provider, switch the config back to `FALLBACK_PROVIDER`/`FALLBACK_MODEL`.
4. When the access token has < 7 days left, renew silently.

```bash
cp scripts/check.py scripts/codebuddy_login.py scripts/codebuddy_guard.sh ~/.hermes/codebuddy/
chmod 700 ~/.hermes/codebuddy/*.py ~/.hermes/codebuddy/*.sh
# Hermes cron: script must live under ~/.hermes/scripts/
ln -sf ~/.hermes/codebuddy/codebuddy_guard.sh ~/.hermes/scripts/codebuddy_guard.sh
```

Then create a cron job (`no_agent: true`, schedule `0 10 * * *`, script `codebuddy_guard.sh`, deliver to your chat).

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `400` `code 11101` "Non-stream chat request is currently not supported" | Sent `stream: false` | Always stream; auxiliary calls that need non-stream must use another provider |
| `401` on every request | Wrong/missing `X-Domain`, or expired token | Use the `domain` from the token response; refresh |
| `403` `code 11140` | Account flagged by risk control | Stop retrying; it is account-level, not fixable by code |
| Empty `content`, only `reasoning_content` | Reasoning model burned the budget on thinking | Raise `max_tokens` (≥ 64 for probes, much higher for real work) |
| Tool calls arrive malformed | Same budget problem | Raise `max_tokens`; a truncated stream yields half-empty `arguments` |
| Config change has no effect | Running Hermes process caches the provider | `hermes gateway restart` (or `/model` in-session) |
| `TLS` errors / timeouts in China | Direct GitHub/upstream flakiness | Retry, or route through a proxy you control |

## Security & privacy

- Credentials live in `~/.hermes/codebuddy/credentials.json` (`0600`) and `.env` (`0600`) — never in `config.yaml`, never in git.
- This repo contains **no** account identifiers, tokens, hostnames, or IP addresses. Fill in your own in `config.yaml` only.
- One account, one user. **Do not build account pools, credit farming, or multi-account rotation** — it violates the provider's ToS and the ban lands on your account.
- The token is a bearer credential: anyone who reads it can spend your quota.

## FAQ

**Does this work with the international WorkBuddy client?**
The protocol shape is similar but the host, `platform` parameter and User-Agent differ. This repo targets the mainland `copilot.tencent.com` service (`platform=ide`).

**Will Hermes' auxiliary tasks (titles, summaries) work?**
Only if they stream. CodeBuddy rejects non-stream requests, so point auxiliary models at a different provider.

**Why not just use the official API key?**
If you have one, use it. This project exists for subscription/credit-based accounts that only expose the IDE login flow.

**Is this stable?**
It is an undocumented protocol. Endpoints and headers can change without notice. Watch the probe in cron; that is what the guard is for.

## Disclaimer

This is an **unofficial, community-built** integration. It is not affiliated with Tencent, CodeBuddy, or Nous Research. You are responsible for complying with the provider's Terms of Service and with any local regulations. The authors provide no warranty and accept no liability for account restrictions, data loss, or quota consumption. Use at your own risk.

## License

[MIT](LICENSE)
