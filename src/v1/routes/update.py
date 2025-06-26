# Local Imports
from src.config import config, status_config
from ..src.handlers import fetch_and_check_user, update_items
from ..src.constants import inventory_key, sale_key, inventory_id_key, sale_id_key
from ..src.db_firebase import get_db

# External Imports
from fastapi.concurrency import run_in_threadpool
from slowapi.util import get_remote_address
from fastapi import HTTPException, Request, APIRouter
from fastapi import BackgroundTasks
from slowapi import Limiter

import traceback
import asyncio

# Initialize router and rate limiter
router = APIRouter()
limiter = Limiter(key_func=get_remote_address)


@router.get("/")
@limiter.limit("1/second")
async def root(request: Request):
    return config


# Update inventory endpoint
@router.post("/inventory")
@limiter.limit("3/second")
async def update_inventory(request: Request, background_tasks: BackgroundTasks):
    store_type = request.query_params.get("store_type")
    if (not store_type): 
        raise HTTPException(
            status_code=500,
            detail=f"Argument store_type was not provided",
        )

    if (status_config["api"].get(store_type)) != "active":
        return config

    user = None
    user_ref = None
    limits = None
    db = None
    try:
        user_ref, user, limits = await fetch_and_check_user(
            request, store_type, inventory_key
        )
        db = get_db()

        # Check if any of (user, user_ref, limits and db) are None
        if not (user and user_ref and limits and db):
            print(traceback.format_exc())
            raise HTTPException(
                status_code=500,
                detail=f"Unknown error occured updating {inventory_key}",
            )

    except Exception as error:
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(error))

    try:
        def wrapped_update():
            asyncio.run(update_items(
                store_type,
                inventory_key,
                inventory_id_key,
                db,
                user,
                user_ref,
                limits,
                request
            ))

        # Offload the async function to a background thread via a sync wrapper
        background_tasks.add_task(asyncio.to_thread, wrapped_update)

        return {"success": True}

    except Exception as error:
        raise HTTPException(status_code=500, detail=str(error))


# Update orders endpoint
@router.post("/orders")
@limiter.limit("3/second")
async def update_orders(request: Request, background_tasks: BackgroundTasks):
    store_type = request.query_params.get("store_type")
    if not store_type:
        raise HTTPException(
            status_code=500,
            detail=f"Argument store_type was not provided",
        )

    if (status_config["api"].get(store_type)) != "active":
        print(status_config["api"].get(store_type))
        return config

    user = None
    user_ref = None
    limits = None
    db = None
    try:
        user_ref, user, limits = await fetch_and_check_user(
            request, store_type, sale_key
        )
        db = get_db()

        # Check if any of (user, user_ref, limits and db) are None
        if not (user and user_ref and limits and db):
            print(traceback.format_exc())
            raise HTTPException(
                status_code=500, detail=f"Unknown error occured updating {sale_key}"
            )

    except Exception as error:
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(error))

    try:
        def wrapped_update():
            asyncio.run(update_items(
                store_type,
                sale_key,
                sale_id_key,
                db,
                user,
                user_ref,
                limits,
                request
            ))

        # Offload the CPU-bound task to a thread pool
        background_tasks.add_task(asyncio.to_thread, wrapped_update)

        return {"success": True}
    except Exception as error:
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(error))
