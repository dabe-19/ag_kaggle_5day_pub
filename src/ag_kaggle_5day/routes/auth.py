import logging

from fastapi import APIRouter, HTTPException, Request, Response

from ag_kaggle_5day.models import ConnectRequest
from ag_kaggle_5day.security import encrypt_key

logger = logging.getLogger("streamer_advisor.routes.auth")
router = APIRouter()


@router.post("/api/auth/connect")
def connect_key(req: ConnectRequest, response: Response, request: Request):
    key = req.api_key.strip()
    if not key:
        raise HTTPException(status_code=400, detail="API key is required.")

    # Validate key via google-genai
    try:
        from google import genai

        client = genai.Client(api_key=key)
        client.models.list(config={"page_size": 1})
    except Exception as e:
        logger.error(f"API key validation failed: {e}")
        raise HTTPException(status_code=401, detail="Invalid Google AI Studio API key.")

    # Encrypt key
    encrypted = encrypt_key(key)

    # Set cookie dynamically based on HTTPS or HTTP
    secure_cookie = request.url.scheme == "https"
    max_age = 3600 if req.remember else None  # 1 hour if remember, else session cookie
    response.set_cookie(
        key="gemini_session_key",
        value=encrypted,
        httponly=True,
        secure=secure_cookie,
        samesite="lax",
        max_age=max_age,
    )
    return {"status": "connected"}


@router.post("/api/auth/disconnect")
def disconnect_key(response: Response):
    response.delete_cookie("gemini_session_key")
    return {"status": "disconnected"}
