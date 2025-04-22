# Local Imports
from src.utils import ratelimit_error
from src.config import title, description, version, config
from src.v1.routes import update as update_v1_routes

# External Imports
from fastapi.middleware.cors import CORSMiddleware
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from fastapi import FastAPI, Request
from slowapi import Limiter

import uvicorn


# Initialize Limiter
limiter = Limiter(key_func=get_remote_address)

# Initialize FastAPI application
app = FastAPI(
    title=title,
    description=description,
    version=version,
)

# Attach the limiter to the FastAPI app
app.state.limiter = limiter

app.add_exception_handler(RateLimitExceeded, ratelimit_error)

# Setup CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://flippify.io",
        "https://partnerships.flippify.io",
        "http://localhost:3000",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["X-Requested-With", "Authorization", "Content-Type"],
)

# V1 Routes
app.include_router(update_v1_routes.router, prefix="/v1/update", tags=["update v1"])


@app.get("/")
@limiter.limit("1/second")
async def root(request: Request):
    return config


@app.get("/status")
@limiter.limit("3/second")
async def status(request: Request):
    return config["status"]


# Run app if executed directly
#if __name__ == "__main__":
    # When running locally
    #uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
