<h1 align="center">QoderGate</h1>

<p align="center">
  把多个 Qoder 账号统一转换成 OpenAI 兼容接口的本地网关。<br>
  A local gateway that turns multiple Qoder accounts into one OpenAI-compatible API.
</p>

<p align="center">
  <a href="https://github.com/Arimayuki03/QoderGateway/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/Arimayuki03/QoderGateway/ci.yml?label=CI&logo=github" alt="CI"></a>
  <img src="https://img.shields.io/badge/python-%3E%3D3.11-blue?logo=python&logoColor=white" alt="Python >= 3.11">
  <img src="https://img.shields.io/badge/fastapi-0.115+-green?logo=fastapi&logoColor=white" alt="FastAPI">
  <img src="https://img.shields.io/badge/license-MIT-orange" alt="License">
  <a href="https://linux.do"><img src="https://img.shields.io/badge/LINUX_DO-%E7%A4%BE%E5%8C%BA-blue" alt="LINUX DO"></a>
</p>

---

## 致谢 / Acknowledgment

本项目思路来源于 [cubk1/qoder2api](https://github.com/cubk1/qoder2api/)，在此基础上用 Python 重写了后端并新增了 WebUI 管理控制台、SQLite 持久化、多账号池轮转和独立文档站。

This project is inspired by [cubk1/qoder2api](https://github.com/cubk1/qoder2api/). We rewrote the backend in Python and added a WebUI management console, SQLite persistence, multi-account pool rotation, and a standalone documentation site.

特别感谢 [LINUX DO](https://linux.do) 社区提供的交流与推广平台。

Special thanks to the [LINUX DO](https://linux.do) community for the platform of exchange and promotion.

## 功能 / Features

- **OpenAI 兼容接口** — 通过 `/v1/chat/completions` 向客户端提供标准 Chat Completions API，支持流式响应、Thinking 折叠与工具调用
- **多账号池** — 导入多个 Qoder 账号，按 UID 自动去重，请求失败时自动冷却并轮转到下一个账号
- **多种导入方式** — 设备授权登录（生成授权 URL，浏览器确认即入库）、粘贴 PAT/Token、批量导入注册机导出的 JSON
- **两层鉴权** — 管理后台口令与外部 API Key 分开配置；管理端带失败锁定（5 次失败锁 15 分钟）与请求冷却
- **SQLite 持久化** — 账号、API Key、全局配置全部存入本地数据库；重复导入同 UID 保留原有状态
- **WebUI 控制台** — Dashboard、账号池、AI Playground（可停止生成）、API Key 管理、自动注册机、服务日志，窄屏自适应
- **内置注册机** — 基于 YYDS Mail 临时邮箱 + 浏览器自动化批量注册，成功账号自动入库
- **独立注册机 CLI** — [`qodergate-register/`](qodergate-register/README.md) 可脱离网关单独运行，导出 JSON 供网关批量导入
- **安全加固** — 无默认口令（首次启动随机生成）、常量时间比较、安全响应头（含 CSP）、敏感日志打码、可配置出站代理
- **独立文档站** — `/documents` 提供中英文 Wiki，支持本地搜索和目录跳转，按浏览器语言自动切换

## 快速开始 / Quickstart

### 安装 / Install

```bash
git clone https://github.com/Arimayuki03/QoderGateway.git
cd QoderGateway
uv sync
```

### 前端构建 / Build Frontend

```bash
cd frontend
npm install
npm run build
cd ..
```

构建产物会输出到 `src/qoder2api/static/`，后端启动时直接托管 WebUI 与文档站。

### 配置 / Configure

```bash
cp .env.example .env
```

编辑 `.env`，修改管理员密码：

```env
QODER_ADMIN_PASSWORD=your-strong-password
```

> **注意：`QODER_ADMIN_PASSWORD` 只在首次建库时生效（写入 SQLite），
> 之后以控制台存储的口令为准，可在 WebUI 中修改。**
> **首次启动若留空，系统会自动生成随机口令并打印到控制台（仅显示这一次，请妥善保存），
> 不再使用默认口令 `admin`；也可设置 `QODER_ADMIN_PASSWORD` 后删除数据库重建。**

### 导入账号 / Import Accounts

在控制台「账号池」页任选一种方式：

1. **设备授权登录** — 点击设备授权按钮，打开生成的授权 URL，在浏览器中登录 Qoder 后凭据自动入库（授权 URL 5 分钟有效）
2. **手动导入** — 粘贴 PAT 或 Token，按 UID 自动去重
3. **批量导入** — 粘贴注册机导出的 `accounts.json`，一次导入多个账号
4. **自动注册机** — 配置 YYDS Mail API Key 后在控制台一键批量注册

### 内置注册机 / Built-in Registrar

使用内置批量注册功能前，需在 `.env` 或系统环境变量中配置 YYDS Mail API Key：

```env
YYDS_API_KEY=AC-xxxxxxxxxxxxxxxxxxxxxxxx
```

| 变量 | 必填 | 说明 |
|------|------|------|
| `YYDS_API_KEY` | 注册机必填 | YYDS Mail API Key（`AC-` 开头），用于创建临时邮箱并接收验证码 |

### 启动 / Start

```bash
uv run qoder2api
```

服务默认运行在 `http://127.0.0.1:5050/`。

| 路径 | 说明 |
|------|------|
| `/` | Landing Page |
| `/console` | 管理控制台 |
| `/documents` | 文档站 / Wiki |
| `/v1/chat/completions` | OpenAI 兼容 API |

### 第一次 API 调用 / First API Call

在控制台导入账号后：

```bash
curl http://127.0.0.1:5050/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "lite",
    "messages": [{ "role": "user", "content": "Hello" }],
    "stream": false
  }'
```

## 独立注册机 / Standalone Registrar

`qodergate-register/` 是从网关注册机模块独立提取的 CLI，无网关依赖，可单独批量注册并导出 JSON：

```bash
cd qodergate-register
uv sync
uv run python -m qodergate_register --parents 2      # 2 个母线程（每批 3 子任务并发）
uv run python -m qodergate_register --check          # 检查 YYDS_API_KEY 配置
```

成功注册的账号自动导出 `accounts.json`，可在网关控制台「账号池 → 批量导入」直接粘贴导入。人机验证（滑块）需人工完成：浏览器平时隐藏后台，验证时自动置顶。详见 [qodergate-register/README.md](qodergate-register/README.md)。

## 环境变量 / Environment Variables

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `QODER_HOST` | 服务绑定地址 | `127.0.0.1` |
| `QODER_PORT` | 服务端口 | `5050` |
| `QODER_ADMIN_PASSWORD` | 管理员密码（仅首次建库时生效，之后以 SQLite/WebUI 为准；留空则首次启动随机生成并打印） | 随机生成 |
| `YYDS_API_KEY` | YYDS Mail API Key（内置注册机必填，`AC-` 开头） | 空 |
| `QODER_PROXY` | 出站代理地址（作用于上游请求、Token 刷新、注册机浏览器） | 空 |
| `QODER_ENABLE_DOCUMENTS` | 是否启用文档页 | `1` |
| `QODER_ENABLE_LANDING` | 是否启用 Landing Page | `1` |
| `QODER_PAT` | 首次启动时自动导入的 PAT | 空 |

## 项目结构 / Project Structure

```
├── src/qoder2api/          # Python 后端
│   ├── app.py              # FastAPI 路由（控制台 / OpenAI 兼容 API / 注册机 / 设备授权）
│   ├── accounts.py         # SQLite 账号管理
│   ├── auth.py             # 网关鉴权、口令哈希与失败锁定
│   ├── bridge.py           # OpenAI 兼容响应转换（流式 / 工具调用 / usage）
│   ├── config.py           # 配置读写
│   ├── database.py         # SQLite schema
│   ├── encoding.py         # 请求/响应编码处理
│   ├── env.py              # 环境变量加载
│   ├── registrar.py        # 内置注册机（YYDS Mail + 浏览器自动化）
│   ├── signature.py        # Qoder 请求签名
│   ├── tokens.py           # Token 刷新与设备授权流程
│   └── static/             # 前端构建产物
├── frontend/               # React 前端源码
│   ├── src/App.tsx         # 管理控制台
│   ├── src/docs-main.tsx   # 文档站
│   ├── src/landing-main.tsx# Landing Page
│   └── src/docs/           # 中英文 Markdown 文档
├── qodergate-register/     # 独立注册机 CLI（python -m qodergate_register）
├── scripts/                # 注册流程逆向分析辅助脚本
├── docs/                   # 协议研究笔记（qoder-protocol-research.md）
├── tests/                  # 后端单元测试（46 项，标准库 unittest）
├── .github/workflows/      # CI（后端测试 + 前端 tsc/构建）
├── .env.example            # 环境变量模板
└── pyproject.toml          # 项目配置
```

## 测试 / Testing

后端包含 46 项单元测试，基于标准库 `unittest`，运行时会自动把数据库指向临时目录（`QODER_DB_PATH`），不会触碰真实的 `~/.qoder` 数据：

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
```

前端类型检查与构建：

```bash
cd frontend && npx tsc --noEmit && npm run build
```

以上检查由 GitHub Actions 在每次 push / PR 时自动运行（`.github/workflows/ci.yml`）。

## License

MIT
