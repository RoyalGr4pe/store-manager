# Local Imports
from ..db_firebase import FirebaseDB
from ..constants import (
    history_limits,
    max_ebay_order_limit_per_page,
    max_ebay_listing_limit_per_page,
    inventory_key,
    sale_key,
    MAX_WHILE_LOOP_DEPTH,
)
from .extract import (
    extract_refund_data,
    extract_shipping_details,
    extract_time_key,
)
from ..models import IUser, OrderStatus, IdKey
from ..utils import (
    format_date_to_iso,
    fetch_user_member_sub,
    was_order_created_in_current_month,
    fetch_user_inventory_and_orders_count,
)

# External Imports
from google.cloud.firestore_v1 import AsyncDocumentReference
from ebaysdk.trading import Connection as Trading
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

import traceback
import os


load_dotenv()


# --------------------------------------------------- #
# eBay Inventory Processing                           #
# --------------------------------------------------- #


async def fetch_ebay_listings(limit: int, db: FirebaseDB, user: IUser, user_ref: AsyncDocumentReference, **kwargs):
    # Step 1: Extract kwargs
    id_key = kwargs.get("id_key")
    oauth_token: str = user.connectedAccounts.ebay.ebayAccessToken
    page = 1

    user_count = await fetch_user_inventory_and_orders_count(user, user_ref, db)

    # Step 2: Calculate the number of item slots the user has left
    available_slots = limit - user_count["automaticListings"]

    items = []
    force_update = False
    while_loop_count = 0
    try:
        while available_slots > 0:
            if while_loop_count >= MAX_WHILE_LOOP_DEPTH:
                raise Exception("Max while loop depth reached")
            while_loop_count += 1

            # Step 3: Query eBay for users listings
            listings, total_pages = await fetch_listings_from_ebay(
                oauth_token, limit, page
            )

            if not listings or not isinstance(listings, list):
                break

            # Step 4: Process the listings
            items, new_items_count, available_slots, force_update = await process_listings(
                listings, user, db, available_slots, id_key
            )

            # Step 5: If there are no more pages or available slots, break the loop
            if (total_pages and page >= int(total_pages)) or available_slots <= 0:
                break

            # Step 6: Move to the next page
            page += 1

        return {"content": items, "new": new_items_count, "force_update": force_update}

    except Exception as error:
        print(traceback.format_exc())
        raise error


async def fetch_listings_from_ebay(oauth_token: str, limit: int, page: int):
    api = Trading(
        appid=os.getenv("CLIENT_ID"),
        devid=os.getenv("DEV_ID"),
        certid=os.getenv("CLIENT_SECRET"),
        token=oauth_token,
        config_file=None,
    )

    max_per_page = (
        max_ebay_listing_limit_per_page
        if limit > max_ebay_listing_limit_per_page
        else limit
    )

    params = {
        "ActiveList": {
            "Include": True,
            "Sort": "TimeLeft",
            "Pagination": {
                "EntriesPerPage": max_per_page,
                "PageNumber": page,
            },
        }
    }

    response = api.execute("GetMyeBaySelling", params)
    response_dict = response.dict()

    items = response_dict.get("ActiveList", {}).get("ItemArray", {}).get("Item", [])
    pagenation = response_dict.get("ActiveList", {}).get("PaginationResult", {})
    total_pages: str | None = pagenation.get("TotalNumberOfPages")

    return items, total_pages


async def process_listings(
    listings: list, user: IUser, db: FirebaseDB, available_slots: int, id_key: IdKey
):
    items, new_items_count, force_update = [], 0, False

    try:
        # Step 1: Create a list of ids from the listing
        listing_ids = [listing["ItemID"] for listing in listings if "ItemID" in listing]

        # Step 2: Query all the listings in the database which have a listing id contained in the above list
        db_listings_map = await db.get_items_by_ids(
            user.id, listing_ids, inventory_key, "ebay", id_key
        )

        for listing in listings:
            # Step 3: Get the db listing from the map
            db_listing = db_listings_map.get(listing["ItemID"])

            if db_listing is None:
                # Step 5: If the db listing doesn't exist then this is a new listing, so increment the below values
                new_items_count += 1
                available_slots -= 1

            # Step 4: Check if the quantity is zero, if it is then ignore this listing, if it is zero and the listing exists in the database, then remove it
            quantity = int(listing.get("QuantityAvailable", 0))
            if quantity == 0 and db_listing is not None:
                await db.remove_item(user.id, listing["ItemID"], inventory_key, "ebay")
                new_items_count -= 1
                force_update = True
            elif quantity == 0:
                continue

            # Step 6: Create the listing dictionary
            item = {
                "createdAt": format_date_to_iso(datetime.now()),
                "currency": listing["BuyItNowPrice"]["_currencyID"],
                "dateListed": listing["ListingDetails"]["StartTime"],
                "image": [listing["PictureDetails"]["GalleryURL"]],
                "initialQuantity": int(listing["Quantity"]),
                "itemId": listing["ItemID"],
                "name": listing["Title"],
                "price": round(
                    float(listing["SellingStatus"]["CurrentPrice"]["value"]), 2
                ),
                "quantity": quantity,
                "recordType": "automatic",
                "url": listing["ListingDetails"]["ViewItemURL"],
                "lastModified": format_date_to_iso(datetime.now(timezone.utc)),
                "ebay": {
                    "type": listing["ListingType"],
                },
                "storeType": "ebay"
            }

            if check_for_listing_changes(item, db_listing):
                # Step 7: If the item is different from the db listing then append the listing data to items so it gets update/added
                items.append(item)

            # Step 8: If no more available slots, stop processing
            if available_slots <= 0:
                return items, new_items_count, available_slots

        return items, new_items_count, available_slots, force_update

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
        "initialQuantity",
        "itemId",
        "name",
        "price",
        "quantity",
        "url",
    ]

    # Loop through fields and return True as soon as a discrepancy is detected.
    for field in fields_to_check:
        if new_listing.get(field) != db_listing.get(field):
            return True

    # No changes detected in the key fields.
    return False


def fetch_listing_details_from_ebay(item_id: str, oauth_token: str):
    # Make a call to the eBay API to fetch the listing details
    api = Trading(
        appid=os.getenv("CLIENT_ID"),
        devid=os.getenv("DEV_ID"),
        certid=os.getenv("CLIENT_SECRET"),
        token=oauth_token,
        config_file=None,
    )

    response = api.execute("GetItem", {"ItemID": item_id})

    if response and "Item" in response.dict():
        item = response.dict()["Item"]
        image_path = item.get("PictureDetails", {}).get("PictureURL")
        if image_path is None or len(image_path) == 0:
            image = None
        else:
            image = image_path[0]

        return {
            "image": image,
            "dateListed": item.get("ListingDetails", {}).get("StartTime"),
        }

    return {}


# --------------------------------------------------- #
# eBay Order Processing                               #
# --------------------------------------------------- #


async def fetch_ebay_orders(limit: int, db: FirebaseDB, user: IUser, user_ref: AsyncDocumentReference, **kwargs):
    # Step 1: Extract kwargs
    oauth_token: str = user.connectedAccounts.ebay.ebayAccessToken
    new_items_count, old_items_count, page = 0, 0, 1

    if (user.store.storeMeta.get("ebay") is None):
        return

    # Step 2: Determine the time to start fetch orders
    time_from = user.store.storeMeta["ebay"].lastFetchedDate.orders
    if not time_from:
        time_from = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
        user_sub = fetch_user_member_sub(user)
        limit = history_limits.get(user_sub.name)

    # Step 3: If time from is older then a certain time, then search for orders using CreateTimeFrom else use ModTimeFrom
    key = extract_time_key(time_from)

    user_count = await fetch_user_inventory_and_orders_count(user, user_ref, db)

    # Step 4: Calculate the number of item slots the user has left
    available_slots = limit - user_count["automaticOrders"]

    items = []
    while_loop_count = 0
    try:
        while available_slots > 0:
            if while_loop_count >= MAX_WHILE_LOOP_DEPTH:
                raise Exception("Max while loop depth reached")
            while_loop_count += 1

            # Step 5: Query eBay for the users orders
            orders, has_more_orders = await fetch_orders_from_ebay(
                oauth_token, time_from, key, limit, page
            )

            if not orders:
                break

            # Step 6: Process the orders
            (items, new_items_count, old_items_count, available_slots) = (
                await process_orders(
                    orders,
                    db,
                    user.id,
                    oauth_token,
                    new_items_count,
                    old_items_count,
                    available_slots,
                )
            )

            # Step 7: If there are no more orders or slots, break the loop
            if not has_more_orders or available_slots <= 0:
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


async def fetch_orders_from_ebay(
    oauth_token: str, time_from: str, key: str, limit: int, page: int
):
    """
    Fetch orders from the eBay API with pagination.
    """
    api = Trading(
        appid=os.getenv("CLIENT_ID"),
        devid=os.getenv("DEV_ID"),
        certid=os.getenv("CLIENT_SECRET"),
        token=oauth_token,
        config_file=None,
    )

    # Set the maximum limit per page if the users subscription limit is greater then this limit
    max_per_page = (
        max_ebay_order_limit_per_page
        if limit > max_ebay_order_limit_per_page
        else limit
    )

    params = {
        "OrderStatus": "All",
        key: time_from,
        "Pagination": {
            "EntriesPerPage": max_per_page,
            "PageNumber": page,
        },
    }

    response = api.execute("GetOrders", params)
    response_dict: dict = response.dict()
    has_more_orders: bool = response_dict.get("HasMoreOrders", False)

    order_array: dict = response_dict.get("OrderArray")
    if order_array is None:
        return [], False

    orders = order_array.get("Order", [])

    return orders, has_more_orders


async def process_orders(
    orders: list[dict],
    db: FirebaseDB,
    uid: str,
    oauth_token: str,
    new_items_count: int,
    old_items_count: int,
    available_slots: int,
):
    items = []
    try:
        for order in orders:
            transactions: list[dict] = order.get("TransactionArray", {}).get(
                "Transaction", []
            )
            if not isinstance(transactions, list):
                transactions = [transactions]

            for transaction in transactions:
                # Step 1: Retrieve the order from the database
                res = await db.retrieve_item(
                    uid, transaction.get("TransactionID"), sale_key, "ebay"
                )
                db_transaction = res.get("item")

                if db_transaction is None:
                    # Step 2: Handle if the order doesn't exist in the database
                    item = await handle_new_order(
                        db, uid, oauth_token, order, transaction
                    )
                    if not item:
                        continue

                    # Step 3: Determine if the item is new or old
                    if was_order_created_in_current_month(item):
                        new_items_count += 1
                    else:
                        old_items_count += 1

                    # Step 4: This item is new with available space so append it to items
                    items.append(item)
                    available_slots -= 1

                else:
                    # Step 5: Handle of the order does exist in the database
                    item = await handle_modified_order(
                        order, transaction, db_transaction
                    )
                    if item:
                        # Step 6: This item isn't new so don't increase the order count, but add the item so it gets updated
                        items.append(item)

                # Step 7: If no more available slots, stop processing
                if available_slots <= 0:
                    return (items, new_items_count, old_items_count, available_slots)

        return (items, new_items_count, old_items_count, available_slots)

    except Exception as error:
        print(traceback.format_exc())
        raise error


async def handle_new_order(
    db: FirebaseDB,
    uid: str,
    oauth_token: str,
    order: dict,
    transaction: dict,
):
    try:
        # Order
        order_status: OrderStatus = order["OrderStatus"]
        total_sale_price = float(order["AmountPaid"]["value"])
        modification_date = order["CheckoutStatus"]["LastModifiedTime"]
        is_cancelled = order_status == "Cancelled"

        # Transaction
        item_id = transaction["Item"]["ItemID"]
        transaction_id = transaction["TransactionID"]
        quantity_sold = int(transaction["QuantityPurchased"])
        sale_price = quantity_sold * float(transaction["TransactionPrice"]["value"])

        # Refunds
        refund = None
        if order_status in ["CancelPending", "Cancelled"]:
            refund = extract_refund_data(order, is_cancelled)

        # Listing
        listing_data: dict = await get_listing_for_order(db, uid, item_id, oauth_token)

        # Shipping
        shipping = extract_shipping_details(
            order, transaction.get("ShippingDetails", {})
        )

        additional_fees = (
            0.0
            if is_cancelled
            else round(total_sale_price - sale_price - shipping["fees"], 2)
        )

        return {
            "additionalFees": additional_fees,
            "createdAt": format_date_to_iso(datetime.now()),
            "customTag": listing_data.get("customTag"),
            "transactionId": transaction_id,
            "name": transaction["Item"]["Title"],
            "itemId": item_id,
            "image": listing_data.get("image"),
            "orderId": order["OrderID"],
            "purchase": listing_data["purchase"],
            "recordType": "automatic",
            "listingDate": listing_data["dateListed"],
            "sale": {
                "currency": transaction["TransactionPrice"].get("_currencyID"),
                "date": order["CreatedTime"],
                "platform": transaction["Item"].get("Site", "eBay"),
                "price": sale_price,
                "quantity": quantity_sold,
                "buyerUsername": order["BuyerUserID"],
            },
            "shipping": shipping,
            "status": order_status,
            "storeType": "ebay",
            "refund": refund,
            "lastModified": modification_date,
        }

    except Exception as error:
        print(traceback.format_exc())
        raise error


async def handle_modified_order(
    order: dict,
    transaction: dict,
    db_transaction: dict,
) -> dict:
    """
    Compare the existing database transaction to the newly modified order,
    apply updates if needed, and return the updated order.
    """
    try:
        order_status = order["OrderStatus"]
        total_sale_price = float(order["AmountPaid"]["value"])
        modification_date = order["CheckoutStatus"]["LastModifiedTime"]
        is_cancelled = order_status == "Cancelled"

        item_name = transaction["Item"]["Title"]
        quantity_sold = int(transaction["QuantityPurchased"])
        sale_price = quantity_sold * float(transaction["TransactionPrice"]["value"])

        refund = (
            extract_refund_data(order, is_cancelled)
            if order_status in ["CancelPending", "Cancelled"]
            else None
        )
        new_shipping = extract_shipping_details(
            order, transaction.get("ShippingDetails", {})
        )
        new_additional_fees = (
            0.0
            if is_cancelled
            else round(total_sale_price - sale_price - new_shipping.get("fees", 0), 2)
        )

        updated_order = db_transaction.copy()
        changes_found = False

        # Define fields to compare and update
        update_map = [
            ("additionalFees", new_additional_fees),
            ("shipping", new_shipping),
            ("status", order_status),
            ("refund", refund),
            ("name", item_name),
        ]

        # Compare and update simple fields
        for key, new_value in update_map:
            if updated_order.get(key) != new_value:
                updated_order[key] = new_value
                changes_found = True

        # Compare nested sale.price
        if updated_order.get("sale", {}).get("price") != sale_price:
            updated_order["sale"]["price"] = sale_price
            changes_found = True

        # Compare nested sale.quantity
        if updated_order.get("sale", {}).get("quantity") != quantity_sold:
            updated_order["sale"]["quantity"] = quantity_sold
            changes_found = True

        # Update history and last modified date if anything changed
        if changes_found:
            updated_order["lastModified"] = modification_date

        return updated_order

    except Exception as error:
        print(traceback.format_exc())
        raise error


async def get_listing_for_order(
    db: FirebaseDB,
    uid: str,
    item_id: str,
    oauth_token: str,
) -> dict:
    """
    Retrieve and format listing data for a given order.

    If listing data is not found in the database, fetch details from eBay.
    If the order is completed, decrease the listing quantity.

    Returns:
        A dictionary containing the listing details.
    """
    data = {}
    try:
        listing_res = await db.retrieve_item(uid, item_id, inventory_key, "ebay")
        listing_data = listing_res.get("item")

        if not listing_data:
            listing_data = fetch_listing_details_from_ebay(item_id, oauth_token)

        if listing_data:
            purchase_info: dict = listing_data.get("purchase", {})
            listing_data["purchase"] = {
                "currency": listing_data.get("currency"),
                "date": listing_data.get("dateListed"),
                "platform": purchase_info.get("platform"),
                "price": purchase_info.get("price"),
                "quantity": listing_data.get("initialQuantity"),
            }
            data = listing_data

        return data

    except Exception as error:
        print(traceback.format_exc())
        raise error
