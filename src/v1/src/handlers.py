# Local Imports
from .db_firebase import get_db, FirebaseDB
from .models import (
    IStore,
    IUser,
    INumOrders,
    INumListings,
    ILastFetchedDate,
    IOffset,
    StoreType,
    ItemType,
    IdKey,
    StoreEntry
)
from .utils import (
    format_date_to_iso,
    get_next_month_reset_date,
    fetch_user_member_sub,
    fetch_users_limits,
    fetch_user_inventory_and_orders_count,
)
from .constants import inventory_key, sale_key

# Depop
# from .depop.handler import fetch_depop_listings, fetch_depop_orders

# eBay
from .ebay.handler import fetch_ebay_listings, fetch_ebay_orders
from .ebay.tokens import check_and_refresh_ebay_token

# External Imports
from google.cloud.firestore_v1 import AsyncDocumentReference
from datetime import datetime, timezone
from fastapi import HTTPException, Request

import traceback

fetch_functions = {
    "ebay-inventory": fetch_ebay_listings,
    "ebay-orders": fetch_ebay_orders,
    #    "depop-inventory": fetch_depop_listings,
    #    "depop-orders": fetch_depop_orders,
}


async def fetch_and_check_user(
    request: Request, store_type: StoreType, item_type: ItemType
):
    try:
        # Step 1: Check a uid was passed in with the url
        uid = request.query_params.get("uid")
        if uid is None:
            return HTTPException(
                status_code=401, detail="Unauthorized: No valid uid provided"
            )

        # Step 2: Fetch the user from the database
        db = get_db()
        user_ref = await db.query_user_ref(uid)
        user_snapshot = await user_ref.get()
        user_doc = user_snapshot.to_dict()

        # Step 3: Check if the user has any account connected
        connected_accounts: dict | None = user_doc.get("connectedAccounts", {})
        if not connected_accounts:
            return HTTPException(
                status_code=401, detail=f"Unauthorized: No account not connected"
            )

        # Step 4: Check if the user has connected their (store_type) account
        account: dict | None = connected_accounts.get(store_type)
        if not account:
            return HTTPException(
                status_code=401,
                detail=f"Unauthorized: {store_type} account not connected",
            )

        # Step 5: Create a user object, add any missing store information, reset the totals if current date later then reset date
        user = add_and_update_store(IUser(**user_doc), store_type)

        # Step 6: Confirm the user has a valid subscription
        member_subscription = fetch_user_member_sub(user)
        if not member_subscription:
            raise HTTPException(
                status_code=400, detail="User does not have a valid subscription"
            )

        # Step 7: Fetch the subscription limits
        limits: dict = fetch_users_limits(member_subscription.name, item_type)

        # Step 8: Check to see if the user has reached their automatic limit
        max_automatic_limit: int = limits["automatic"]
        user_count = await fetch_user_inventory_and_orders_count(user, user_ref, db)

        if user_count["automaticOrders"] >= max_automatic_limit:
            raise HTTPException(
                status_code=400, detail="User has reached their automatic limit"
            )

        # Step 9: Execute any custom functions required for a store
        store_res = await handle_store(store_type, request, db, user_ref, user)
        if store_res.get("error"):
            raise HTTPException(status_code=500, detail=store_res.get("error"))
        user: IUser = store_res.get("user")

        return user_ref, user, limits

    except Exception as error:
        print(traceback.format_exc())
        return HTTPException(status_code=500, detail=str(error))


def add_and_update_store(user: IUser, store_type: StoreType) -> IUser:
    # Step 1: Ensure the user has a store container
    if user.store is None:
        user.store = {}

   # Step 2: Add numListings if missing
    if not isinstance(getattr(user.store, "numListings", None), INumListings):
        user.store.numListings = INumListings(automatic=0, manual=0)

    # Step 3: Add numOrders if missing
    if not isinstance(getattr(user.store, "numOrders", None), INumOrders):
        reset_date = get_next_month_reset_date()
        user.store.numOrders = INumOrders(
            resetDate=format_date_to_iso(reset_date),
            automatic=0,
            manual=0,
            totalAutomatic=0,
            totalManual=0,
        )

    # Step 4: Add storeType-specific info (e.g., offset, lastFetchedDate)
    store_meta = user.store.storeMeta.get(store_type)
    if not store_meta:
        store_meta = StoreEntry()
        user.store.storeMeta[store_type] = store_meta

    # Ensure offset and lastFetchedDate exist
    if store_meta.lastFetchedDate is None:
        store_meta.lastFetchedDate = ILastFetchedDate(inventory=None, orders=None)
    if store_meta.offset is None:
        store_meta.offset = IOffset(inventory=None, orders=None)

    return user


async def handle_store(
    store_type: StoreType,
    request: Request,
    db: FirebaseDB,
    user_ref: AsyncDocumentReference,
    user: IUser,
):
    match store_type:
        case "ebay":
            return await check_and_refresh_ebay_token(request, db, user_ref, user)
        case _:
            return {"success": True, "user": user}


async def update_items(
    store_type: StoreType,
    item_type: ItemType,
    id_key: IdKey,
    db: FirebaseDB,
    user: IUser,
    user_ref: AsyncDocumentReference,
    limits: dict,
    request: Request,
):
    try:
        # Step 1: Fetch related function
        fetch_func = fetch_functions[f"{store_type}-{item_type}"]

        # Step 2: Execute
        res: dict = await fetch_func(
            limits["automatic"], db, user, user_ref, id_key=id_key
        )

        # Step 3: Extract
        items = res.get("content")
        force_update = res.get("force_update", False)
        new_items_count = res.get("new", 0)
        old_items_count = res.get("old", 0)
        offset = res.get("offset")

        # Step 4: Update
        await update_db(
            items,
            new_items_count,
            old_items_count,
            offset,
            user,
            user_ref,
            db,
            item_type,
            store_type,
            id_key,
            force_update
        )

        return {"success": True}
    except Exception as error:
        print(traceback.format_exc())
        raise error


async def update_db(
    items: list,
    new_items_count: int,
    old_items_count: int,
    offset: str | None,
    user: IUser,
    user_ref: AsyncDocumentReference,
    db: FirebaseDB,
    item_type: ItemType,
    store_type: StoreType,
    id_key: IdKey,
    force_update: bool
):
    try:
        if not items and not force_update:
            return

        # Step 1: Add items to that database
        res = await db.add_items(user.id, items, item_type, store_type, id_key)
        if not res.get("success"):
            raise Exception(res.get("message"))

        # Step 2: Add the date the items were added
        await db.set_last_fetched_date(
            user_ref,
            item_type,
            format_date_to_iso(datetime.now(timezone.utc)),
            store_type,
        )

        if offset:
            # Step 3: Add offset if it is provided
            await db.set_offset(user_ref, item_type, offset, store_type)

        # Step 4: Set the number of items for the given store type
        if item_type == inventory_key:
            await db.set_current_no_listings(
                user_ref,
                user.store.numListings.automatic,
                new_items_count,
                user.store.numListings.manual,
            )
        elif item_type == sale_key:
            await db.set_current_no_orders(
                user_ref,
                user.store.numOrders,
                new_items_count,
                old_items_count,
            )

    except Exception as error:
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(error))
