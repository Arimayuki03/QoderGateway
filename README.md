<h1 align="center">QoderGateway</h1>

<p align="center">
  <strong>把多个 Qoder 账号统一转换成 OpenAI 兼容接口的本地网关</strong><br>
  <sub>A local gateway that turns multiple Qoder accounts into one OpenAI-compatible API.</sub>
</p>

<p align="center">
  <a href="https://github.com/Arimayuki03/QoderGateway/releases"><img src="https://img.shields.io/github/v/release/Arimayuki03/QoderGateway?logo=github&label=release" alt="Release"></a>
  <a href="https://github.com/Arimayuki03/QoderGateway/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/Arimayuki03/QoderGateway/ci.yml?label=CI&logo=github" alt="CI"></a>
  <a href="https://github.com/Arimayuki03/QoderGateway/stargazers"><img src="https://img.shields.io/github/stars/Arimayuki03/QoderGateway?logo=github&color=yellow" alt="Stars"></a>
  <a href="https://github.com/bzym2/QoderGateway"><img src="https://img.shields.io/badge/fork_of-bzym2%2FQoderGateway-8A2BE2?logo=github" alt="Fork of bzym2/QoderGateway"></a>
  <img src="https://img.shields.io/badge/python-%3E%3D3.11-blue?logo=python&logoColor=white" alt="Python >= 3.11">
  <img src="https://img.shields.io/badge/fastapi-0.115+-green?logo=fastapi&logoColor=white" alt="FastAPI">
  <img src="https://img.shields.io/badge/license-MIT-orange" alt="License">
  <a href="https://linux.do"><img src="https://img.shields.io/badge/LINUX_DO-%E7%A4%BE%E5%8C%BA-blue" alt="LINUX DO"></a>
</p>

<p align="center">
  <a href="#-功能特性">功能特性</a> ·
  <a href="#-快速开始">快速开始</a> ·
  <a href="#-配置">配置</a> ·
  <a href="#-api-示例">API 示例</a> ·
  <a href="#-文档与支持">文档</a> ·
  <a href="#-致谢">致谢</a>
</p>

---

## 📖 简介

QoderGateway 是一个运行在本地的 **账号池网关**：导入多个 Qoder 账号后，对外提供统一的 OpenAI 兼容接口（`/v1/chat/completions`）。请求自动在账号池中轮转，单个账号失败自动冷却并切换下一个；配套的 WebUI 控制台支持账号管理、API Key 管理、AI Playground、设备授权登录和自动注册机。

> **[Fork 说明]** 本仓库 fork 自 [bzym2/QoderGateway](https://github.com/bzym2/QoderGateway)，并在此基础上进行维护与增强。

- 🌐 **中英文档站内置**：启动后访问 [`/documents`](http://127.0.0.1:5050/documents) 获取完整 Wiki
- 🔌 **OpenAI 兼容**：任何支持自定义 Base URL 的客户端（Cherry Studio、LobeChat、Open WebUI 等）均可直接接入
- 🔐 **两层鉴权**：管理后台口令与外部 API Key 相互独立

## ✨ 功能特性

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

## 🚀 快速开始

### 前置要求

| 依赖 | 版本 | 说明 |
|------|------|------|
| [uv](https://docs.astral.sh/uv/) | 最新版 | Python 包与虚拟环境管理 |
| Python | ≥ 3.11 | 由 `uv sync` 自动准备 |
| Node.js | ≥ 20 | 仅构建前端时需要 |

### 1. 安装

```bash
git clone https://github.com/Arimayuki03/QoderGateway.git
cd QoderGateway
uv sync
```

### 2. 构建前端

```bash
cd frontend
npm install
npm run build
cd ..
```

构建产物输出到 `src/qoder2api/static/`，后端启动时直接托管 WebUI 与文档站。

### 3. 配置

```bash
cp .env.example .env
```

编辑 `.env`，修改管理员密码：

```env
QODER_ADMIN_PASSWORD=your-strong-password
```

> **注意：`QODER_ADMIN_PASSWORD` 只在首次建库时生效（写入 SQLite），之后以控制台存储的口令为准，可在 WebUI 中修改。**
> **首次启动若留空，系统会自动生成随机口令并打印到控制台（仅显示这一次，请妥善保存）。**

### 4. 启动

```bash
uv run qoder2api
```

服务默认运行在 `http://127.0.0.1:5050/`：

| 路径 | 说明 |
|------|------|
| `/` | Landing Page |
| `/console` | 管理控制台 |
| `/documents` | 文档站 / Wiki |
| `/v1/chat/completions` | OpenAI 兼容 API |

### 5. 导入账号

打开控制台 [`/console`](http://127.0.0.1:5050/console)，在「账号池」页任选一种方式：

1. **设备授权登录** — 点击设备授权按钮，打开生成的授权 URL，在浏览器中登录 Qoder 后凭据自动入库（授权 URL 5 分钟有效）
2. **手动导入** — 粘贴 PAT 或 Token，按 UID 自动去重
3. **批量导入** — 粘贴注册机导出的 `accounts.json`，一次导入多个账号
4. **自动注册机** — 配置 YYDS Mail API Key 后在控制台一键批量注册

## 🔑 API 示例

在控制台创建 API Key 后（或在「服务设置」中启用免鉴权）：

```bash
curl http://127.0.0.1:5050/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -d '{
    "model": "lite",
    "messages": [{ "role": "user", "content": "Hello" }],
    "stream": false
  }'
```

任何支持自定义 OpenAI Base URL 的客户端都可以直接接入：

| 设置项 | 值 |
|--------|-----|
| API Base URL | `http://127.0.0.1:5050/v1` |
| API Key | 控制台创建的 Key |
| 模型 | `lite` |

## ⚙️ 配置

### 环境变量

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

### 内置注册机

使用内置批量注册功能前，需在 `.env` 或系统环境变量中配置 YYDS Mail API Key：

```env
YYDS_API_KEY=AC-xxxxxxxxxxxxxxxxxxxxxxxx
```

## 🤖 独立注册机

[`qodergate-register/`](qodergate-register/README.md) 是从网关注册机模块独立提取的 CLI，无网关依赖，可单独批量注册并导出 JSON：

```bash
cd qodergate-register
uv sync
uv run python -m qodergate_register --parents 2      # 2 个母线程（每批 3 子任务并发）
uv run python -m qodergate_register --check          # 检查 YYDS_API_KEY 配置
```

成功注册的账号自动导出 `accounts.json`，可在网关控制台「账号池 → 批量导入」直接粘贴导入。人机验证（滑块）需人工完成：浏览器平时隐藏后台，验证时自动置顶。详见 [qodergate-register/README.md](qodergate-register/README.md)。

## 🧪 测试

后端包含 47 项单元测试，基于标准库 `unittest`，运行时会自动把数据库指向临时目录（`QODER_DB_PATH`），不会触碰真实的 `~/.qoder` 数据：

```bash
uv run python -m unittest discover -s tests -v
```

前端类型检查与构建：

```bash
cd frontend && npx tsc --noEmit && npm run build
```

以上检查由 GitHub Actions 在每次 push / PR 时自动运行（`.github/workflows/ci.yml`）。

## 📁 项目结构

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
├── tests/                  # 后端单元测试（47 项，标准库 unittest）
├── .github/workflows/      # CI（后端测试 + 前端 tsc/构建）
├── .env.example            # 环境变量模板
└── pyproject.toml          # 项目配置
```

## 🗺️ 路线图

- [x] OpenAI 兼容接口与流式响应
- [x] 多账号池轮转与自动冷却
- [x] WebUI 管理控制台
- [x] 设备授权登录导入
- [x] 内置 / 独立自动注册机
- [x] 中英文档站
- [ ] Docker 镜像与一键部署
- [ ] 更多上游模型支持

## 🤝 贡献

欢迎 Issue 与 PR！提交前请确保：

1. 后端测试通过：`uv run python -m unittest discover -s tests -v`
2. 前端类型检查通过：`cd frontend && npx tsc --noEmit`
3. 新功能请附上相应说明与测试

## 📄 License

本项目基于 [MIT License](LICENSE) 开源。

## 💗 致谢

- 本项目 fork 自 [bzym2/QoderGateway](https://github.com/bzym2/QoderGateway)，原项目受 [cubk1/qoder2api](https://github.com/cubk1/qoder2api/) 启发，用 Python 重写了后端并新增了 WebUI 管理控制台、SQLite 持久化、多账号池轮转和独立文档站
- 感谢原作者 [bzym2](https://github.com/bzym2) 的工作，本仓库在此基础上继续维护与增强
- 特别感谢 [LINUX DO](https://linux.do) 社区提供的交流与推广平台
