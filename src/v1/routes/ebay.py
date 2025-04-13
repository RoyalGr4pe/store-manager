# Local Imports
from ..src.utils import (
    fetch_user_member_sub,
    fetch_users_limits,
    get_next_month_reset_date,
    format_date_to_iso,
)
from src.config import api_status
from ..src.models import Store, IStore, INumListings, INumOrders
from ..src.ebay.tokens import fetch_user_and_update_tokens
from ..src.ebay.db_firebase import get_db
from ..src.ebay.handler_ebay import (
    update_ebay_inventory,
    update_ebay_orders,
)

# External Imports
from slowapi.util import get_remote_address
from fastapi import HTTPException, Request, APIRouter
from slowapi import Limiter
from pprint import pprint

import traceback


# Initialize router and rate limiter
router = APIRouter()
limiter = Limiter(key_func=get_remote_address)


@router.get("/")
@limiter.limit("1/second")
async def root(request: Request):
    return api_status


# Update inventory endpoint
@router.post("/update-inventory")
@limiter.limit("3/second")
async def update_inventory(request: Request):
    # return api_status

    try:
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

    except Exception as error:
        print("Error in update_inventory() | 1 ", error)
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(error))

    errors = []

    try:
        if not user.store:
            user.store = Store()

        store = user.store

        if not store.ebay:
            reset_date = get_next_month_reset_date()
            store.ebay = IStore(
                numListings=INumListings(automatic=0, manual=0),
                numOrders=INumOrders(
                    resetDate=format_date_to_iso(reset_date),
                    automatic=0,
                    manual=0,
                    totalAutomatic=0,
                    totalManual=0,
                ),
            )

        ebay_update = await update_ebay_inventory(
            store.ebay, db, user, user_ref, user_limits
        )
        if ebay_update.get("error"):
            errors.append(ebay_update.get("error"))

        if errors:
            return {"success": False, "errors": errors}

        return {"success": True}

    except Exception as error:
        print("Error in update_inventory() | 2 ", error)
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(error))


# Update orders endpoint
@router.post("/update-orders")
@limiter.limit("3/second")
async def update_orders(request: Request):
    # return api_status

    try:
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

    except Exception as error:
        print("Error in update_orders() | 1 ", error)
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(error))

    errors = []

    try:
        if not user.store:
            user.store = Store()

        store = user.store

        reset_date = get_next_month_reset_date()
        if not store.ebay:
            store.ebay = IStore(
                numListings=INumListings(automatic=0, manual=0),
                numOrders=INumOrders(
                    resetDate=format_date_to_iso(reset_date),
                    automatic=0,
                    manual=0,
                    totalAutomatic=0,
                    totalManual=0,
                ),
            )

        ebay = store.ebay

        if not ebay.numOrders:
            ebay.numOrders = INumOrders(
                resetDate=format_date_to_iso(reset_date),
                automatic=0,
                manual=0,
                totalAutomatic=0,
                totalManual=0,
            )

        ebay_update = await update_ebay_orders(ebay, db, user, user_ref, user_limits)
        if ebay_update.get("error"):
            errors.append(ebay_update.get("error"))

        if errors:
            return {"success": False, "errors": errors}

        return {"success": True}

    except Exception as error:
        print("Error in update_orders() | 2 ", error)
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(error))
