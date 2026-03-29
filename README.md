# bookmark-ai-service

[中文](./README_zh.md) | English

`bookmark-ai-service` is the AI backend service for Smart Bookmark Keeper.

It receives bookmark context from the Chrome extension, requests a structured organization plan from the model, validates and normalizes returned actions, and enforces a daily usage limit with SQLite.

## Features

- `POST /api/bookmarks/plan` for AI organization plans
- `GET /api/bookmarks/usage` for daily quota status
- SQLite-based daily request limit per `clientId`
- Action validation and normalization before returning results
- OpenAI-compatible AI API integration

## Stack

- Python
- FastAPI
- Uvicorn
- httpx
- python-dotenv
- SQLite

## Quick Start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload
```

The service reads model configuration from `.env`.

## Environment Variables

- `AI_API_BASE`
- `AI_API_KEY`
- `AI_MODEL`
- `SQLITE_DB_PATH`
- `DAILY_REQUEST_LIMIT`
- `HOST`
- `PORT`

## API Endpoints

- `GET /health`
- `GET /api/bookmarks/usage`
- `POST /api/bookmarks/plan`

## Project Structure

- `app/main.py`: FastAPI entrypoint
- `app/ai_service.py`: model request, parsing, and action normalization
- `app/config.py`: environment-based configuration
- `app/schemas.py`: request and response models
- `app/usage_service.py`: SQLite usage limit logic
- `tests/`: service tests
- `scripts/run_service.sh`: local startup script

## Notes

- The service works with OpenAI-compatible chat completion APIs
- Daily usage is tracked per `clientId` in SQLite
- Quota windows are calculated in `Asia/Shanghai`
- The service is intended to generate plans only and should not persist bookmark content

## Use Your Own Key

1. Copy the example environment file:

```bash
cp .env.example .env
```

2. Open `.env` and set your own AI provider configuration:

```env
AI_API_BASE=https://your-provider.example.com/v1
AI_API_KEY=your_own_key_here
AI_MODEL=your_model_name
```

3. Start the service:

```bash
uvicorn app.main:app --reload
```

If you deploy this service publicly, it is recommended to use HTTPS and add your own server-side authentication.
