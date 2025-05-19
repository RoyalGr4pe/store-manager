from ..src.models import IUser, ISubscription, INumListings, INumOrders
from google.cloud.firestore_v1 import AsyncDocumentReference

from datetime import datetime, timezone

import json


def fetch_user_member_sub(user: IUser) -> ISubscription | None:
    user_subscriptions_list = user.subscriptions
    if not user_subscriptions_list:
        return False

    user_has_member_subscription = False
    user_subscription = None

    for sub in user_subscriptions_list:
        if "member" in sub.name:
            user_has_member_subscription = True
            user_subscription = sub
            break

    if not user_has_member_subscription:
        return False

    return user_subscription


# Determines how many listings and orders each subscription user can have
def fetch_sub_limits_dict(filename="sub-limits.json"):
    with open(filename, "r") as file:
        return json.load(file)


def fetch_users_limits(sub_name, limit_type):
    sub_limits_dict = fetch_sub_limits_dict()
    limits = sub_limits_dict[limit_type]

    # Extract the first work of the subscription
    # i.e. Standard - member -> standard
    formatted_sub_name = sub_name.split(" ")[0].lower()

    # Dict which looks something like for listings
    # {
    #    "automatic": 300,
    #    "manual": 300
    # }
    return limits[formatted_sub_name]


def get_next_month_reset_date() -> datetime:
    """Returns the first of the next month as an ISO string."""
    # Use timezone-aware datetime with UTC
    today = datetime.now(timezone.utc)

    # Calculate the first day of the next month
    if today.month == 12:
        next_month = today.replace(year=today.year + 1, month=1, day=1)
    else:
        next_month = today.replace(month=today.month + 1, day=1)

    # Return the date as an ISO string in UTC format
    return next_month


def format_date_to_iso(date: datetime) -> str:
    """Helper function to format dates to the required ISO 8601 format (e.g., 2024-11-01T17:12:26.000Z)."""
    return date.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def was_order_created_in_current_month(order: dict):
    current_date = datetime.now()
    current_month = current_date.month
    current_year = current_date.year

    sale_info = order.get("sale", {})
    paid_time = sale_info.get("date")

    if not paid_time:
        return None  # Skip orders with no valid sale date

    paid_date = datetime.fromisoformat(
        paid_time.replace("Z", "+00:00").replace(" ", "")
    )

    if paid_date.month == current_month and paid_date.year == current_year:
        return True
    else:
        return False


async def fetch_user_inventory_and_orders_count(
    user: IUser, user_ref: AsyncDocumentReference, db
) -> dict[str, int]:
    """
    Returns a dictionary with counts of automatic/manual listings and orders.
    If resetDate has passed, order counts are reset and excluded from totals.
    """

    if not user.store:
        return {
            "automaticListings": 0,
            "manualListings": 0,
            "automaticOrders": 0,
            "manualOrders": 0,
        }

    today = datetime.now(timezone.utc).date()

    automatic_listings = 0
    manual_listings = 0
    automatic_orders = 0
    manual_orders = 0

    store_data = user.store

    # --- Listings ---
    if isinstance(getattr(store_data, "numListings", None), INumListings):
        automatic_listings += store_data.numListings.automatic or 0
        manual_listings += store_data.numListings.manual or 0

    # --- Orders ---
    auto, manual = 0, 0
    reset_needed = False
    store_type_key = None  # We'll track the first found store type (like 'ebay') to call reset if needed

    if isinstance(getattr(store_data, "numOrders", None), INumOrders):
        reset_str = store_data.numOrders.resetDate
        reset_date = None

        if reset_str:
            try:
                reset_date = (
                    datetime.fromisoformat(reset_str).date()
                    if "T" in reset_str else datetime.strptime(reset_str, "%Y-%m-%d").date()
                )
            except Exception:
                reset_date = None

        if reset_date and today > reset_date:
            reset_needed = True
        else:
            auto = store_data.numOrders.automatic or 0
            manual = store_data.numOrders.manual or 0

    automatic_orders += auto
    manual_orders += manual

    # --- Optional: Reset in Firestore if needed ---
    if reset_needed:
        for key, value in store_data.items():
            if isinstance(value, dict) and "lastFetchedDate" in value:
                store_type_key = key
                break
        if store_type_key:
            await db.reset_current_no_orders(user_ref, store_type_key)

    return {
        "automaticListings": automatic_listings,
        "manualListings": manual_listings,
        "automaticOrders": automatic_orders,
        "manualOrders": manual_orders,
    }