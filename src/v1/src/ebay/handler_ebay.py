# Local Imports
from ..ebay.db_firebase import FirebaseDB
from ..ebay.constants import (
    history_limits,
    max_ebay_order_limit_per_page,
    max_ebay_listing_limit_per_page,
)
from ..ebay.extract import (
    extract_history_data,
    extract_refund_data,
    extract_shipping_details,
    extract_time_key,
)
from ..models import (
    IStore,
    IUser,
    INumOrders,
    INumListings,
    OrderStatus,
)
from ..utils import (
    get_next_month_reset_date,
    format_date_to_iso,
    fetch_user_member_sub,
    was_order_created_in_current_month,
)

# External Imports
from google.cloud.firestore_v1 import AsyncDocumentReference
from ebaysdk.exception import ConnectionError
from ebaysdk.trading import Connection as Trading
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
from pprint import pprint

import traceback
import os


load_dotenv()


# --------------------------------------------------- #
# eBay Inventory Processing                           #
# --------------------------------------------------- #


async def update_ebay_inventory(
    ebay: IStore,
    db: FirebaseDB,
    user: IUser,
    user_ref: AsyncDocumentReference,
    user_limits: dict,
) -> None:
    try:
        if not ebay.numListings:
            ebay.numListings = INumListings(automatic=0, manual=0)

        ebay_listings_dict = await fetch_ebay_listings(
            user.connectedAccounts.ebay.ebayAccessToken,
            user_limits["automatic"],
            db,
            user,
        )
        ebay_listings = ebay_listings_dict.get("content")
        new_listings = ebay_listings_dict.get("new", 0)

        if not ebay_listings:
            return {"content": []}

        await db.add_listings(user.id, ebay_listings)
        await db.set_last_fetched_date(
            user_ref,
            "inventory",
            format_date_to_iso(datetime.now(timezone.utc)),
            "ebay",
        )
        await db.set_current_no_listings(
            user_ref,
            ebay.numListings.automatic,
            new_listings,
            ebay.numListings.manual,
            "ebay",
        )

        return {"success": True}
    except Exception as error:
        print("update_ebay_inventory() error:", error)
        print(traceback.format_exc())
        return {"error": error}


async def fetch_ebay_listings(
    oauth_token: str, limit: int, db: FirebaseDB, user: IUser
):
    api = Trading(
        appid=os.getenv("CLIENT_ID"),
        devid=os.getenv("DEV_ID"),
        certid=os.getenv("CLIENT_SECRET"),
        token=oauth_token,
        config_file=None,
    )

    listings = []
    new_listing_count = 0
    page = 1
    error = None

    max_per_page = (
        max_ebay_listing_limit_per_page
        if limit > max_ebay_listing_limit_per_page
        else limit
    )

    try:
        while True:
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

            items = (
                response_dict.get("ActiveList", {}).get("ItemArray", {}).get("Item", [])
            )
            if not items:
                break

            if not isinstance(items, list):
                items = [items]

            item_ids = [item["ItemID"] for item in items if "ItemID" in item]
            db_listings_map = await db.get_listings_by_ids(user.id, item_ids)

            for item in items[::-1]:
                item_id = item["ItemID"]
                db_listing_dict = db_listings_map.get(item_id)
                db_listing = db_listing_dict.get("listing") if db_listing_dict else None

                if db_listing is None:
                    if (
                        user.store.ebay.numListings.automatic + new_listing_count
                        >= limit
                    ):
                        continue
                    new_listing_count += 1

                quantity = int(item.get("QuantityAvailable", 0))
                if quantity == 0:
                    continue

                listing_data = {
                    "currency": item["BuyItNowPrice"]["_currencyID"],
                    "dateListed": item["ListingDetails"]["StartTime"],
                    "image": [item["PictureDetails"]["GalleryURL"]],
                    "initialQuantity": int(item["Quantity"]),
                    "itemId": item_id,
                    "name": item["Title"],
                    "price": round(
                        float(item["SellingStatus"]["CurrentPrice"]["value"]), 2
                    ),
                    "type": item["ListingType"],
                    "quantity": quantity,
                    "recordType": "automatic",
                    "url": item["ListingDetails"]["ViewItemURL"],
                    "lastModified": format_date_to_iso(datetime.now(timezone.utc)),
                }

                if check_for_listing_changes(listing_data, db_listing):
                    listings.append(listing_data)

            pagenation_result: dict | None = response_dict.get("ActiveList", {}).get(
                "PaginationResult", {}
            )
            if not pagenation_result:
                break

            total_pages: str | None = pagenation_result.get("TotalNumberOfPages")
            if (total_pages) and (page >= int(total_pages)):
                break
            
            page += 1

    except ConnectionError as e:
        error = e
        print(traceback.format_exc())

    except Exception as e:
        error = e
        print("error in fetch_ebay_listings:", error)
        print(traceback.format_exc())

    return {"content": listings, "new": new_listing_count, "error": error}


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


async def update_ebay_orders(
    ebay: IStore,
    db: FirebaseDB,
    user: IUser,
    user_ref: AsyncDocumentReference,
    user_limits: dict,
) -> None:
    try:
        if not ebay.numOrders:
            ebay.numOrders = INumOrders(
                resetDate=format_date_to_iso(get_next_month_reset_date()),
                automatic=0,
                manual=0,
                totalAutomatic=0,
                totalManual=0,
            )

        current_time = datetime.now(timezone.utc)
        time_from = (
            None  # ebay.lastFetchedDate.orders if ebay.lastFetchedDate else None
        )
        first_lookup = False
        if not time_from:
            first_lookup = True
            time_from = (current_time - timedelta(days=90)).isoformat()
        else:
            time_from = ebay.lastFetchedDate.orders

        reset_auto = await db.check_and_reset_automatic_date(
            user_ref, ebay.numOrders, user_limits
        )
        if reset_auto["success"] == False:
            return {"error": reset_auto["error"]}

        await fetch_ebay_orders(
            db,
            user.id,
            user_ref,
            user,
            user.connectedAccounts.ebay.ebayAccessToken,
            user_limits["automatic"],
            time_from,
            first_lookup,
            reset_auto["available"],
        )

        await db.set_last_fetched_date(
            user_ref, "orders", format_date_to_iso(current_time), "ebay"
        )

        return {"success": True}
    except Exception as error:
        print("update_ebay_orders() error:", error)
        print(traceback.format_exc())
        return {"error": error}


async def fetch_ebay_orders(
    db: FirebaseDB,
    uid: str,
    user_ref: AsyncDocumentReference,
    user: IUser,
    oauth_token: str,
    limit: int,
    time_from: str,
    first_lookup: bool,
    available_slots: int,
    page: int = 1,
):
    api = Trading(
        appid=os.getenv("CLIENT_ID"),
        devid=os.getenv("DEV_ID"),
        certid=os.getenv("CLIENT_SECRET"),
        token=oauth_token,
        config_file=None,
    )

    if first_lookup:
        user_sub = fetch_user_member_sub(user)
        limit = history_limits.get(user_sub.name, "Free - member")

    key = extract_time_key(time_from)

    new_orders, old_orders = 0, 0

    try:
        while available_slots > 0:
            # Fetch the eBay orders for the given page
            orders, has_more_orders = await fetch_orders_from_ebay(
                api, time_from, key, limit, page
            )

            if not orders:
                break

            # Process the orders
            new_orders, old_orders, available_slots = await process_orders(
                orders,
                db,
                uid,
                user_ref,
                user,
                oauth_token,
                new_orders,
                old_orders,
                available_slots,
            )

            # If there are no more orders or slots, break the loop
            if not has_more_orders or available_slots <= 0:
                break

            # Move to the next page
            page += 1

        return {"success": True, "error": None}

    except Exception as error:
        print("error in fetch_ebay_orders", error)
        print(traceback.format_exc())
        return {"success": False, "error": error}


async def fetch_orders_from_ebay(
    api: Trading, time_from: str, key: str, limit: int, page: int
):
    """
    Fetch orders from the eBay API with pagination.
    """

    # Set the maximum limit per page if the users subscription limit is greater then this limit
    use_limit = (
        max_ebay_order_limit_per_page
        if limit > max_ebay_order_limit_per_page
        else limit
    )

    params = {
        "OrderStatus": "All",
        key: time_from,
        "Pagination": {
            "EntriesPerPage": use_limit,
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
    orders: list,
    db: FirebaseDB,
    uid: str,
    user_ref: AsyncDocumentReference,
    user: IUser,
    oauth_token: str,
    new_orders: int,
    old_orders: int,
    available_slots: int,
):
    """
    Process the orders and update the database.
    """
    for order in orders:
        transactions = order.get("TransactionArray", {}).get("Transaction", [])
        if not isinstance(transactions, list):
            transactions = [transactions]

        for transaction in transactions:
            transaction_id = transaction.get("TransactionID")
            db_order_result = await db.get_order(uid, transaction_id)
            db_transaction = db_order_result["order"]

            order_info = None
            if db_transaction is None:
                # Handle new order
                order_info = await handle_new_order(
                    db, uid, oauth_token, order, transaction
                )
                if not order_info:
                    continue

                # Determine if the order is new or old
                if was_order_created_in_current_month(order_info):
                    new_orders += 1
                    user.store.ebay.numOrders.automatic += 1
                else:
                    old_orders += 1

                await db.add_orders(uid, [order_info])
                await db.set_current_no_orders(
                    user_ref,
                    user.store.ebay.numOrders,
                    new_orders,
                    old_orders,
                    "ebay",
                )

                available_slots -= 1

            else:
                # Handle modified order
                order_info = await handle_modified_order(
                    order, transaction, db_transaction
                )
                if order_info:
                    await db.add_orders(uid, [order_info])

            if available_slots <= 0:
                # No more available slots, stop processing
                return new_orders, old_orders, available_slots

    return new_orders, old_orders, available_slots


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

        # History
        history = extract_history_data(
            order_status, transaction, shipping, refund, sale_price, modification_date
        )

        return {
            "additionalFees": additional_fees,
            "customTag": listing_data.get("customTag"),
            "transactionId": transaction_id,
            "name": transaction["Item"]["Title"],
            "itemId": item_id,
            "image": listing_data.get("image"),
            "orderId": order["OrderID"],
            "purchase": listing_data["purchase"],
            "recordType": "automatic",
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
            "history": [history],
            "refund": refund,
            "lastModified": format_date_to_iso(datetime.now(timezone.utc)),
        }

    except Exception as error:
        print("error in handle_new_order", error)
        print(traceback.format_exc())


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

        new_history = extract_history_data(
            order_status,
            transaction,
            new_shipping,
            refund,
            sale_price,
            modification_date,
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
            history_list = updated_order.get("history", [])
            if not history_list or new_history != history_list[-1]:
                history_list.append(new_history)
            updated_order["history"] = history_list
            updated_order["lastModified"] = format_date_to_iso(
                datetime.now(timezone.utc)
            )

        return updated_order

    except Exception as error:
        print("error in handle_modified_order:", error)
        print(traceback.format_exc())
        return None


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
        listing_res = await db.get_listing(uid, item_id)
        listing_data = listing_res.get("listing")

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
        print("Error in get_listing_for_order:", error)
        print(traceback.format_exc())
        return {}
