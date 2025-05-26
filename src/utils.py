from fastapi import Request
from slowapi.errors import RateLimitExceeded
from fastapi.responses import JSONResponse

import random
import string

# Add exception handler for rate limit exceeded errors
async def ratelimit_error(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        status_code=429,
        content={"detail": "Rate limit exceeded, please try again later."},
    )


def generate_random_chars(num_char: int) -> str:
    chars = string.ascii_letters + string.digits  # A-Z, a-z, 0-9
    return "".join(random.choice(chars) for _ in range(num_char))


def generate_random_flippify_id(num_char: int = 30) -> str:
    return f"fid-{generate_random_chars(num_char)}"