# Local Imports
from src.utils import fetch_user_member_sub, fetch_users_limits, get_next_month_reset_date
from src.models import IUser, Store, IStore, INumListings, INumOrders
from src.db_firebase import FirebaseDB
from src.handler_ebay import check_and_refresh_ebay_token, update_ebay_inventory, update_ebay_orders

# External Imports
from google.cloud.firestore_v1 import AsyncDocumentReference, DocumentSnapshot
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from fastapi import FastAPI, HTTPException, Request
from slowapi import Limiter

import uvicorn


# Initialize Limiter
limiter = Limiter(key_func=get_remote_address)

# Initialize FastAPI application
app = FastAPI(
    title="Flippify Store API",
    description="API for fetching and updating eBay listings and orders",
    version="1.0.0",
)

# Attach the limiter to the FastAPI app
app.state.limiter = limiter


# Add exception handler for rate limit exceeded errors
async def ratelimit_error(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        status_code=429,
        content={"detail": "Rate limit exceeded, please try again later."},
    )


app.add_exception_handler(RateLimitExceeded, ratelimit_error)

# Setup CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Connect to Mongo and Firebase
db = None


def get_db():
    global db
    if not db:
        db = FirebaseDB()
    return db


# Fetch and authenticate a user based on the provided request.
async def fetch_user_and_update_tokens(
    request: Request,
) -> tuple[AsyncDocumentReference, DocumentSnapshot, IUser] | HTTPException:
    uid = request.query_params.get("uid")
    auth_header = request.headers.get("Authorization")

    token = None
    # Check if the header is present and starts with "Bearer"
    if auth_header and auth_header.startswith("Bearer "):
        # Extract the token after "Bearer "
        token = auth_header.split(" ")[1]
    else:
        return HTTPException(
            status_code=401, detail="Unauthorized: No valid token provided"
        )

    # Fetch the user from the database
    db = get_db()
    user_ref = db.query_user_ref(uid)
    user_snapshot = await user_ref.get()
    user_doc = user_snapshot.to_dict()

    if not user_doc:
        return HTTPException(status_code=404, detail="User not found")

    user = IUser(**user_doc)

    # Check if the user has connected their eBay account
    connected_accounts = user.connectedAccounts
    ebay_account = connected_accounts.ebay
    if not ebay_account:
        return HTTPException(
            status_code=401, detail="Unauthorized: eBay account not connected"
        )

    # Confirm the give access token is the same as the one stored in the database
    if ebay_account.ebayAccessToken != token:
        return HTTPException(
            status_code=401, detail="Unauthorized: Invalid token provided"
        )

    token_update_result = await check_and_refresh_ebay_token(db, user_ref, ebay_account)
    if not token_update_result.get("success"):
        return HTTPException(
            status_code=401,
            detail=f"Unauthorized: Token refresh failed. {token_update_result.get('error')}",
        )

    return user_ref, user_snapshot, user


@app.get("/")
@limiter.limit("1/second")
async def root(request: Request):
    return {"name": "Flippify API", "version": "1.0.1", "status": "running", "docs": "https://api.flippify.io/docs"}


# Update inventory endpoint
@app.get("/update-inventory")
@limiter.limit("1/second")
async def active_listings(request: Request):
    user_info = await fetch_user_and_update_tokens(request)
    if isinstance(user_info, HTTPException):
        raise user_info

    user_ref, _, user = user_info
    member_subscription = fetch_user_member_sub(user)
    if not member_subscription:
        raise HTTPException(
            status_code=400, detail="User does not have a valid subscription"
        )

    user_limits: dict = fetch_users_limits(member_subscription.name, "listings")
    db = get_db()

    errors = []

    try:
        store = user.store
        if not store:
            user.store = Store()

        if (not store.ebay):
            store.ebay = IStore(
                numListings=INumListings(automatic=0, manual=0),
                numOrders=INumOrders(resetDate=get_next_month_reset_date(), automatic=0, manual=0, totalAutomatic=0, totalManual=0),
            )

        ebay = store.ebay

        if (not ebay.numListings):
            ebay.numListings = INumListings(automatic=0, manual=0)

        ebay_update = await update_ebay_inventory(ebay, db, user, user_ref, user_limits)
        if ebay_update.get("error"):
            errors.append(ebay_update.get("error"))

        if (errors):
            return {"success": False, "errors": errors}

        return {"success": True}

    except Exception as error:
        raise HTTPException(status_code=500, detail=str(error))


# Update orders endpoint
@app.get("/update-orders")
@limiter.limit("1/second")
async def orders(request: Request):
    user_info = await fetch_user_and_update_tokens(request)
    if isinstance(user_info, HTTPException):
        raise user_info

    user_ref, _, user = user_info
    member_subscription = fetch_user_member_sub(user)
    if not member_subscription:
        raise HTTPException(
            status_code=400, detail="User does not have a valid subscription"
        )

    user_limits: dict = fetch_users_limits(member_subscription.name, "orders")
    db = get_db()

    errors = []

    try:
        store = user.store
        if not store:
            user.store = Store()

        if (not store.ebay):
            store.ebay = IStore(
                numListings=INumListings(automatic=0, manual=0),
                numOrders=INumOrders(
                    resetDate=get_next_month_reset_date(),
                    automatic=0,
                    manual=0,
                    totalAutomatic=0,
                    totalManual=0,
                ),
            )

        ebay = store.ebay

        if not ebay.numOrders:
            ebay.numOrders = INumOrders(
                resetDate=get_next_month_reset_date(),
                automatic=0,
                manual=0,
                totalAutomatic=0,
                totalManual=0,
            )

        ebay_update = await update_ebay_orders(ebay, db, user, user_ref, user_limits)
        if ebay_update.get("error"):
            errors.append(ebay_update.get("error"))

        if (errors):
            return {"success": False, "errors": errors}

        return {"success": True}

    except Exception as error:
        raise HTTPException(status_code=500, detail=str(error))


# Run app if executed directly
if __name__ == "__main__":
    # When running locally
    uvicorn.run(app, host="0.0.0.0", port=8000)
