from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.ai_service import generate_plan
from app.feedback_service import FeedbackLimitExceededError, init_feedback_db, submit_feedback
from app.schemas import (
    BookmarkPlanRequest,
    BookmarkPlanResponse,
    FeedbackRequest,
    FeedbackResponse,
    UsageResponse,
)
from app.usage_service import DailyLimitExceededError, enforce_daily_limit, get_usage, init_usage_db


app = FastAPI(title="bookmark-ai-service")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup() -> None:
    await init_usage_db()
    await init_feedback_db()


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/bookmarks/usage", response_model=UsageResponse)
async def get_bookmark_usage(clientId: str) -> UsageResponse:
    snapshot = await get_usage(clientId)
    return UsageResponse(
        limit=snapshot.limit,
        used=snapshot.used,
        remaining=snapshot.remaining,
        date=snapshot.date,
    )


@app.post("/api/bookmarks/plan", response_model=BookmarkPlanResponse)
async def create_bookmark_plan(payload: BookmarkPlanRequest) -> BookmarkPlanResponse:
    try:
        await enforce_daily_limit(payload.clientId)
        return await generate_plan(payload)
    except DailyLimitExceededError as error:
        raise HTTPException(
            status_code=429,
            detail={
                "code": "DAILY_LIMIT_EXCEEDED",
                "message": "今日 AI 整理次数已达上限",
                "limit": error.snapshot.limit,
                "used": error.snapshot.used,
                "remaining": error.snapshot.remaining,
                "date": error.snapshot.date,
            },
        ) from error
    except Exception as error:
        raise HTTPException(status_code=500, detail=str(error)) from error


@app.post("/api/feedback", response_model=FeedbackResponse)
async def create_feedback(payload: FeedbackRequest) -> FeedbackResponse:
    try:
        feedback_id = await submit_feedback(
            client_id=payload.clientId,
            content=payload.content,
            contact=payload.contact,
            locale=payload.locale,
            app_version=payload.appVersion,
        )
        return FeedbackResponse(status="ok", id=feedback_id)
    except FeedbackLimitExceededError as error:
        raise HTTPException(
            status_code=429,
            detail={
                "code": "FEEDBACK_LIMIT_EXCEEDED",
                "message": "今日反馈提交次数已达上限",
                "limit": error.snapshot.limit,
                "used": error.snapshot.used,
                "date": error.snapshot.date,
            },
        ) from error
    except Exception as error:
        raise HTTPException(status_code=500, detail=str(error)) from error
