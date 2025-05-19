# Local Imports
from src.config import config, status_config
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
    url = request.query_params.get("url")
    if (not url): 
        raise HTTPException(
            status_code=500,
            detail=f"Argument url was not provided",
        )
    
    if (status_config["api"]["product"]) != "active":
        return config
    
    try:
        html = http_request(url)
        if html is None:
            return {}

        meta = extract_meta(html)
        if meta is None:
            return {}
    
        return parse_product_data(meta)

    except Exception as error:
        print(traceback.format_exc())