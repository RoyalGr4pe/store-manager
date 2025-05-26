from fastapi import Request
from slowapi.errors import RateLimitExceeded
from fastapi.responses import JSONResponse

# Add exception handler for rate limit exceeded errors
async def ratelimit_error(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        status_code=429,
        content={"detail": "Rate limit exceeded, please try again later."},
    )