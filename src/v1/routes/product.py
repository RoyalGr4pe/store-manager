# Local Imports
from src.config import config, status_config
from ..src.handlers import fetch_and_check_user
from ..src.constants import sale_key
from ..src.db_firebase import get_db
from ..src.product.extract import extract_meta, parse_product_data
from ..src.product.send_request import http_request

# External Imports
from slowapi.util import get_remote_address
from fastapi import HTTPException, Request, APIRouter
from slowapi import Limiter

import traceback

# Initialize router and rate limiter
router = APIRouter()
limiter = Limiter(key_func=get_remote_address)



@router.get("/")
@limiter.limit("1/second")
async def root(request: Request):
    return config


@router.get("/retrieve")
@limiter.limit("3/second")
async def retrieve_product(request: Request):
    if (status_config["api"].get("product")) != "active":
        return config
    
    url = request.query_params.get("url")
    store_type = request.query_params.get("store")
    auth_header = request.headers.get("Authorization")

    if (not url or not store_type): 
        raise HTTPException(
            status_code=500,
            detail=f"Arguments not fully provided",
        )
    
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=403,
            detail="Authorization header missing or malformed"
        )
    
    id_token = auth_header.replace("Bearer ", "").strip()

    db = get_db()
    uid = db.retrieve_uid(id_token)

    if (not uid):
        raise HTTPException(
            status_code=403,
            detail=f"Invalid or expired token",
        )
    
    user_ref, user, limits = await fetch_and_check_user(
        request, store_type, sale_key
    )

    if not (user and user_ref and limits and db):
        print(traceback.format_exc())
        raise HTTPException(
            status_code=500, detail=f"Unknown error occured updating {sale_key}"
        )
    
    connected_accounts = user.connectedAccounts

    # Get the connected account dynamically based on the store_type
    connected_account = getattr(connected_accounts, store_type, None)
    

    try:
        html = http_request(url)
        if html is None:
            return {}

        meta = extract_meta(html)
        if meta is None:
            return {}
    
        return parse_product_data(meta, url)

    except Exception as error:
        print(traceback.format_exc())