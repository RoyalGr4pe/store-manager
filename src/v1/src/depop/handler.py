# Local Imports
from ..constants import (
    max_depop_listing_limit_per_page,
    max_depop_order_limit_per_page,
    inventory_key,
    sale_key,
    history_limits,
    MAX_WHILE_LOOP_DEPTH,
)
from ..db_firebase import FirebaseDB
from .contants import inventory_url, sold_url
from ..models import IUser, IdKey, OrderStatus
from .web_req import tls_client_request
from .extract import (
    extract_quantity,
    extract_price,
    extract_shipping,
    extract_history,
    extract_image,
)
from ..utils import (
    format_date_to_iso,
    was_order_created_in_current_month,
    fetch_user_member_sub,
)

# External Imports
from datetime import datetime, timezone

import traceback

# --------------------------------------------------------------- #


async def fetch_depop_listings(limit: int, db: FirebaseDB, user: IUser, **kwargs):
    # Step 1: Extract kwargs
    id_key = kwargs.get("id_key")
    page, offset_id = 1, user.store.depop.offset.inventory

    # Step 2: Calculate the number of item slots the user has left
    available_slots = limit - user.store.depop.numListings.automatic
    while_loop_count = 0

    items = []
    try:
        while available_slots > 0:
            if while_loop_count >= MAX_WHILE_LOOP_DEPTH:
                raise Exception("Max while loop depth reached")
            while_loop_count += 1

            # Step 3: Query depop for the users listings
            listings, meta = await fetch_listings_from_depop(
                limit, user.connectedAccounts.depop.shopId, offset_id
            )
            if not (listings and meta):
                break

            # Step 4: Process the listings
            items, new_items_count, available_slots = await process_listings(
                listings, user, db, available_slots, id_key
            )

            # Step 5: Update offset
            offset_id = meta.get("last_offset_id")

            # Step 6: If there are no more listings or slots, break the loop
            if meta.get("end") or available_slots <= 0:
                break

            # Step 7: Move to the next page
            page += 1

        return {"content": items, "new": new_items_count}

    except Exception as error:
        print(traceback.format_exc())
        raise error


async def fetch_listings_from_depop(limit: int, shop_id: str, offset_id: str):
    max_per_page = (
        max_depop_listing_limit_per_page
        if limit > max_depop_listing_limit_per_page
        else limit
    )

    try:
        url = inventory_url(shop_id, max_per_page, offset_id)
        response: dict | None = await tls_client_request(url)
        if response is None:
            return

        items: list[dict] = response.get("products", [])
        meta: dict = response.get("meta", {})

        return items, meta
    except Exception as error:
        print(traceback.format_exc())
        raise error


async def process_listings(
    listings: list[dict],
    user: IUser,
    db: FirebaseDB,
    available_slots: int,
    id_key: IdKey,
):
    items, new_items_count = [], 0

    try:
        # Step 1: Create a list of ids from the listings
        listing_ids = [str(li["id"]) for li in listings if "id" in li]

        # Step 2: Query all the listings in the database which have a listing id contained in the above list
        db_listings_map = await db.get_items_by_ids(
            user.id, listing_ids, inventory_key, "depop", id_key
        )

        for listing in listings:
            # Step 3: Check if the item has sold
            if listing.get("sold") == True:
                continue

            # Step 4: Check if the quantity is zero, if it is then ignore this listing
            quantity = extract_quantity(listing)
            if quantity == 0 and db_listing is not None:
                db.remove_item(user.id, listing["ItemID"], inventory_key, "depop")
            elif quantity == 0:
                continue

            # Step 5: Get the db listing from the map
            db_listing: dict = db_listings_map.get(str(listing["id"]))

            if db_listing is None:
                # Step 5: If the db listing doesn't exist then this is a new listing, so increment the below values
                new_items_count += 1
                available_slots -= 1

            # Step 6: Extract the largest image
            image = extract_image(listing)

            # Step 7: Extract prices
            original_price, discounted_price = extract_price(listing.get("pricing"))

            # Step 8: Create the listing dictionary
            item = {
                "currency": listing.get("pricing", {}).get("currency_name"),
                "dateListed": (
                    format_date_to_iso(datetime.now(timezone.utc))
                    if db_listing is None
                    else db_listing.get("dateListed")
                ),
                "image": image,
                "initialQuantity": (
                    quantity if not db_listing else db_listing.get("initialQuantity")
                ),
                "itemId": str(listing["id"]),
                "name": listing.get("description"),
                "price": original_price,
                "quantity": quantity,
                "recordType": "automatic",
                "url": f"https://www.depop.com/products/${listing.get('slug', 'not-found')}",
                "lastModified": format_date_to_iso(datetime.now(timezone.utc)),
                "depop": {
                    "discountedPrice": discounted_price,
                    "sizes": listing.get("sizes"),
                    "brandId": listing.get("brand_id"),
                    "categoryId": listing.get("category_id"),
                    "variantSetId": listing.get("variant_set_id"),
                    "variants": listing.get("variants"),
                },
            }

            if check_for_listing_changes(item, db_listing):
                # Step 9: If the item is different from the db listing then append the listing data to items so it gets update/added
                items.append(item)

            # Step 10: If no more available slots, stop processing
            if available_slots <= 0:
                return items, new_items_count, available_slots

        return items, new_items_count, available_slots

    except Exception as error:
        print(traceback.format_exc())
        raise error


def check_for_listing_changes(new_listing: dict, db_listing: dict):
    if db_listing is None:
        return True

    # Define fields to check for updates
    fields_to_check = [
        "currency",
        "dateListed",
        "image",
        "itemId",
        "name",
        "pricing",
        "sizes",
        "variants",
        "url",
    ]

    # Loop through fields and return True as soon as a discrepancy is detected.
    for field in fields_to_check:
        if new_listing.get(field) != db_listing.get(field):
            return True

    # No changes detected in the key fields.
    return False


# --------------------------------------------------------------- #


async def fetch_depop_orders(limit: int, db: FirebaseDB, user: IUser, **kwargs):
    # Step 1: Extract kwargs
    new_items_count, old_items_count, page, offset_id = (
        0,
        0,
        1,
        user.store.depop.offset.orders,
    )

    # Step 2: Fetch the history limit if this is the first lookup
    first_lookup = False
    if user.store.depop.lastFetchedDate.orders is None:
        first_lookup = True
        user_sub = fetch_user_member_sub(user)
        limit = history_limits.get(user_sub.name)

    # Step 4: Calculate the number of item slots the user has left
    available_slots = limit - user.store.depop.numOrders.automatic

    items = []
    while_loop_count = 0
    try:
        while available_slots > 0:
            if while_loop_count >= MAX_WHILE_LOOP_DEPTH:
                raise Exception("Max while loop depth reached")
            while_loop_count += 1

            # Step 4: Query depop for the users orders
            orders, meta = await fetch_orders_from_depop(
                limit, user.connectedAccounts.depop.shopId, offset_id
            )
            if not (orders and meta):
                break

            # Step 5: Process the orders
            (
                items,
                new_items_count,
                old_items_count,
                available_slots,
            ) = await process_orders(
                orders,
                user,
                db,
                new_items_count,
                old_items_count,
                available_slots,
                first_lookup,
            )

            # Step 6: Update offset
            offset_id = meta.get("last_offset_id")

            # Step 7: If there are no more orders or slots, break the loop
            if meta.get("end") or available_slots <= 0:
                break

            # Step 8: Move to the next page
            page += 1

        return {
            "content": items,
            "new": new_items_count,
            "old": old_items_count,
        }

    except Exception as error:
        print(traceback.format_exc())
        raise error


async def fetch_orders_from_depop(limit: int, shop_id: str, offset_id: str):
    max_per_page = (
        max_depop_order_limit_per_page
        if limit > max_depop_order_limit_per_page
        else limit
    )

    try:
        url = sold_url(shop_id, max_per_page, offset_id)
        response: dict | None = await tls_client_request(url)
        if response is None:
            return

        items: list[dict] = response.get("products", [])
        meta: dict = response.get("meta", {})

        return items, meta
    except Exception as error:
        print(traceback.format_exc())
        raise error


async def process_orders(
    orders: list[dict],
    user: IUser,
    db: FirebaseDB,
    new_items_count: int,
    old_items_count: int,
    available_slots: int,
    first_lookup: bool,
):
    items = []
    try:
        print("Orders length", len(orders))
        for order in orders:
            # Step 1: Retrieve the order from the database
            res = await db.retrieve_item(user.id, str(order["id"]), sale_key, "depop")
            db_transaction = res.get("item")
            print("order", order["id"], db_transaction is None)

            if db_transaction is None:
                # Step 2: Handle if the order doesn't exist in the database
                item = await handle_new_order(db, user.id, order)
                if not item:
                    continue

                # Step 3: Determine if the item is new or old
                if was_order_created_in_current_month(item) and not first_lookup:
                    new_items_count += 1
                else:
                    old_items_count += 1

                # Step 4: This item is new with available space so append it to items
                items.append(item)
                available_slots -= 1

            else:
                # Step 5: Handle of the order does exist in the database
                item = await handle_modified_order(order, db_transaction)
                if item:
                    # Step 6: This item isn't new so don't increase the order count, but add the item so it gets updated
                    items.append(item)

            # Step 7: If no more available slots, stop processing
            if available_slots <= 0:
                return (
                    items,
                    new_items_count,
                    old_items_count,
                    available_slots,
                )

        return (
            items,
            new_items_count,
            old_items_count,
            available_slots,
        )

    except Exception as error:
        print(traceback.format_exc())
        raise error


async def handle_new_order(db: FirebaseDB, uid: str, order: dict):
    try:
        # Order
        item_id = str(order["id"])
        order_status: OrderStatus = "Completed"
        pricing: dict = order.get("pricing")

        quantity_sold = 1

        original_price, discounted_price = extract_price(pricing)
        if pricing.get("is_reduced") == True:
            sale_price = quantity_sold * discounted_price
        else:
            sale_price = quantity_sold * original_price

        # Listing
        listing_data: dict = await get_listing_for_order(db, uid, item_id)

        # Shipping
        shipping = extract_shipping(pricing.get("national_shipping_cost", {}))

        # Image
        image = listing_data.get("image") if listing_data else extract_image(order)

        # Current Time
        current_time = format_date_to_iso(datetime.now(timezone.utc))

        # History
        history = extract_history(order_status, current_time)

        return {
            "additionalFees": 0,
            "customTag": listing_data.get("customTag"),
            "transactionId": item_id,
            "name": order.get("description"),
            "itemId": (
                listing_data.get("itemId") if listing_data.get("itemId") else item_id
            ),
            "image": image,
            "purchase": listing_data.get("purchase"),
            "recordType": "automatic",
            "listingDate": listing_data.get("dateListed"),
            "sale": {
                "currency": pricing.get("currency_name"),
                "date": current_time,
                "platform": None,
                "price": sale_price,
                "quantity": quantity_sold,
                "buyerUsername": None,
            },
            "shipping": shipping,
            "status": order_status,
            "history": history,
            "refund": [],
            "lastModified": current_time,
            "depop": {
                "discountedPrice": discounted_price,
                "sizes": order.get("sizes"),
                "brandId": order.get("brand_id"),
                "categoryId": order.get("category_id"),
                "variantSetId": order.get("variant_set_id"),
                "variants": order.get("variants"),
            },
        }

    except Exception as error:
        print(traceback.format_exc())
        raise error


async def handle_modified_order(
    order: dict,
    db_transaction: dict,
):
    updated_order = db_transaction.copy()

    try:
        new_quantity = 1
        pricing = order.get("pricing")
        original_price, discounted_price = extract_price(pricing)
        if pricing.get("is_reduced") == True:
            new_sale_price = new_quantity * discounted_price
        else:
            new_sale_price = new_quantity * original_price

        old_sale_price = db_transaction.get("sale", {}).get("price")

        if new_sale_price != old_sale_price:
            updated_order["sale"]["price"] = new_sale_price

        if order.get("status") != db_transaction.get("status"):
            updated_order["status"] = order.get("status")

    except Exception as error:
        print(traceback.format_exc())
        return None


async def get_listing_for_order(
    db: FirebaseDB,
    uid: str,
    item_id: str,
) -> dict:
    """
    Retrieve and format listing data for a given order.

    If listing data is not found in the database, fetch details from eBay.
    If the order is completed, decrease the listing quantity.

    Returns:
        A dictionary containing the listing details.
    """
    try:
        res = await db.retrieve_item(uid, item_id, inventory_key, "depop")
        data = res.get("item")

        if data:
            purchase_info: dict = data.get("purchase", {})
            data["purchase"] = {
                "currency": data.get("currency"),
                "date": data.get("dateListed"),
                "platform": purchase_info.get("platform"),
                "price": purchase_info.get("price"),
                "quantity": data.get("initialQuantity"),
            }

        return data if data else {}

    except Exception as error:
        print(traceback.format_exc())
        raise error
