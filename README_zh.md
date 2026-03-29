# bookmark-ai-service

中文 | [English](./README.md)

`bookmark-ai-service` 是智能书签管家的 AI 后端服务。

它负责接收 Chrome 扩展传来的书签上下文，请求模型生成结构化整理方案，并在返回前完成动作校验、归一化处理，以及基于 SQLite 的每日调用次数限制。

## 功能特性

- 提供 `POST /api/bookmarks/plan` 用于生成 AI 整理方案
- 提供 `GET /api/bookmarks/usage` 用于查询每日剩余额度
- 基于 SQLite 按 `clientId` 记录每日请求次数
- 在返回前完成动作校验与归一化处理
- 接入兼容 OpenAI 协议的 AI 模型服务

## 技术栈

- Python
- FastAPI
- Uvicorn
- httpx
- python-dotenv
- SQLite

## 快速开始

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload
```

服务启动后会从 `.env` 中读取模型配置。

## 环境变量

- `AI_API_BASE`
- `AI_API_KEY`
- `AI_MODEL`
- `SQLITE_DB_PATH`
- `DAILY_REQUEST_LIMIT`
- `HOST`
- `PORT`

## API 接口

- `GET /health`
- `GET /api/bookmarks/usage`
- `POST /api/bookmarks/plan`

## 项目结构

- `app/main.py`：FastAPI 入口
- `app/ai_service.py`：模型请求、解析和动作归一化
- `app/config.py`：环境变量配置
- `app/schemas.py`：请求与响应模型
- `app/usage_service.py`：SQLite 调用配额逻辑
- `tests/`：服务测试
- `scripts/run_service.sh`：本地启动脚本

## 说明

- 服务使用兼容 OpenAI 协议的聊天补全接口
- 每日调用次数会按 `clientId` 写入 SQLite
- 配额日期窗口按 `Asia/Shanghai` 计算
- 服务仅用于生成整理方案，不应存储书签内容

## 使用您自己的 Key

1. 先复制一份环境变量模板：

```bash
cp .env.example .env
```

2. 打开 `.env`，填入您自己的 AI 服务配置：

```env
AI_API_BASE=https://your-provider.example.com/v1
AI_API_KEY=your_own_key_here
AI_MODEL=your_model_name
```

3. 启动服务：

```bash
uvicorn app.main:app --reload
```

如果您要把服务对公网开放，建议启用 HTTPS，并补充服务端鉴权。
