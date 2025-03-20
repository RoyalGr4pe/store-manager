# Local Imports
from src.utils import get_next_month_reset_date
from src.db_firebase import FirebaseDB
from src.models import (
    EbayTokenData,
    SuccessOrError,
    RefreshEbayTokenData,
    IStore,
    IUser,
    IEbay,
    INumOrders,
    INumListings,
)

# External Imports
from google.cloud.firestore_v1 import AsyncDocumentReference
from ebaysdk.exception import ConnectionError
from ebaysdk.trading import Connection as Trading
from datetime import datetime, timezone, timedelta
from fastapi import HTTPException
from dotenv import load_dotenv

import requests
import base64
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

        if ebay.numListings.automatic >= user_limits["automatic"]:
            raise HTTPException(
                status_code=400,
                detail="You have hit your limit for automatically fetching listings",
            )

        current_time = datetime.now(timezone.utc)
        time_from = ebay.lastFetchedDate.inventory if ebay.lastFetchedDate else None

        if not time_from:
            time_from = (current_time - timedelta(days=90)).isoformat()
        else:
            time_from = ebay.lastFetchedDate.inventory

        ebay_listings_dict = fetch_ebay_listings(
            user.connectedAccounts.ebay.ebayAccessToken,
            user_limits["automatic"],
            time_from,
        )
        ebay_listings = ebay_listings_dict.get("content")

        if not ebay_listings:
            return {"content": []}

        await db.add_listings(user.id, ebay_listings)
        await db.set_last_fetched_date(
            user_ref, "inventory", current_time.isoformat(), "ebay"
        )
        await db.set_current_no_listings(
            user_ref,
            ebay.numListings.automatic + len(ebay_listings),
            ebay.numListings.manual,
            "ebay",
        )

        return {"success": True}
    except Exception as error:
        print("update_ebay_inventory() error:", error)
        return {"error": error}


def fetch_ebay_listings(oauth_token, limit, time_from):
    # Convert time_from to a datetime object
    time_from_date = datetime.fromisoformat(time_from)

    # Connect to eBay API
    api = Trading(
        appid=os.getenv("CLIENT_ID"),
        devid=os.getenv("DEV_ID"),
        certid=os.getenv("CLIENT_SECRET"),
        token=oauth_token,
        config_file=None,
    )

    # Set up parameters for the API call
    params = {
        "ActiveList": {
            "Include": True,
            "Sort": "TimeLeft",  # Sort listings by time remaining
            "StartTimeFrom": time_from,  # Only fetch listings created after this date
            "Pagination": {
                "EntriesPerPage": min(10, limit),  # Limit the number of listings
                "PageNumber": 1,  # Pagination using offset (page number)
            },
        }
    }

    # Parse the response and extract the necessary listing data
    listings = []
    error = None

    try:
        # Make the eBay API call using GetMyeBaySelling
        response = api.execute("GetMyeBaySelling", params)
        response_dict = response.dict()

        items = response_dict.get("ActiveList", {}).get("ItemArray", {}).get("Item", [])
        for item in items[::-1]:
            # Get the date the item was listed
            date_listed = item["ListingDetails"]["StartTime"]
            # Convert the date_listed from string to datetime object
            date_listed_obj = datetime.fromisoformat(date_listed)

            quantity = (
                int(item["QuantityAvailable"]) if "QuantityAvailable" in item else 0
            )
            if quantity == 0:
                continue

            # Check if the date_listed is greater than or equal to time_from
            if date_listed_obj >= time_from_date:
                listing_data = {
                    "itemId": item["ItemID"],
                    "itemName": item["Title"],
                    "price": round(
                        float(item["SellingStatus"]["CurrentPrice"]["value"]), 2
                    ),
                    "image": item["PictureDetails"]["GalleryURL"],
                    "dateListed": date_listed,
                    "recordType": "automatic",
                    "quantity": quantity,
                }
                listings.append(listing_data)

    except ConnectionError as e:
        error = e

    finally:
        return {"content": listings, "error": error}


async def check_and_refresh_ebay_token(
    db: FirebaseDB, user_ref: AsyncDocumentReference, ebay_account: IEbay
) -> SuccessOrError:
    """
    Refresh the eBay access token directly without needing to be called from a route.
    This function assumes the user's Firebase data has a valid refresh token stored.
    """
    try:
        # Check if the users eBay token has expired
        token_expiry = ebay_account.ebayTokenExpiry
        refresh_token = ebay_account.ebayRefreshToken
        current_timestamp = int(datetime.now(timezone.utc).timestamp())

        if token_expiry > current_timestamp:
            return {"success": True}

        # Refresh the eBay access token using the refresh token
        token_data = await refresh_ebay_access_token(
            refresh_token, os.getenv("CLIENT_ID"), os.getenv("CLIENT_SECRET")
        )
        if token_data.data is None:
            return {"success": False, "error": token_data.error}

        # Store the new token and expiry date in the database
        await db.update_user_token(user_ref, token_data.data)

        return {"success": True}
    except Exception as e:
        return {"success": False, "error": f"check_and_refresh_ebay_token(): {str(e)}"}


async def refresh_ebay_access_token(
    refresh_token, client_id, client_secret
) -> RefreshEbayTokenData | None:
    url = "https://api.ebay.com/identity/v1/oauth2/token"

    # Base64 encode the client_id and client_secret
    credentials = f"{client_id}:{client_secret}"
    encoded_credentials = base64.b64encode(credentials.encode("utf-8")).decode("utf-8")

    # Set the authorization header and content-type
    headers = {
        "Authorization": f"Basic {encoded_credentials}",
        "Content-Type": "application/x-www-form-urlencoded",
    }

    # Set the request data (the refresh token and grant type)
    data = {"grant_type": "refresh_token", "refresh_token": refresh_token}

    try:
        # Make the POST request to eBay's token endpoint
        response = requests.post(url, headers=headers, data=data)

        if response.status_code == 200:
            data = response.json()
            return RefreshEbayTokenData(
                data=EbayTokenData(
                    access_token=data["access_token"],
                    expires_in=data["expires_in"],
                    refresh_token=refresh_token,
                ),
                error=None,
            )
        else:
            return RefreshEbayTokenData(
                data=None,
                error=response.text,
            )
    except Exception as error:
        return RefreshEbayTokenData(
            data=None,
            error=f"refresh_ebay_access_token(): {str(error)}",
        )


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
                resetDate=get_next_month_reset_date(),
                automatic=0,
                manual=0,
                totalAutomatic=0,
                totalManual=0,
            )

        if ebay.numOrders.automatic >= user_limits["automatic"]:
            raise HTTPException(
                status_code=400,
                detail="You have hit your limit for automatically fetching orders",
            )

        current_time = datetime.now(timezone.utc)
        time_from = ebay.lastFetchedDate.orders if ebay.lastFetchedDate else None
        if not time_from:
            time_from = (current_time - timedelta(days=90)).isoformat()
        else:
            time_from = ebay.lastFetchedDate.orders

        ebay_orders_dict = await fetch_ebay_orders(
            db,
            user.id,
            user.connectedAccounts.ebay.ebayAccessToken,
            user_limits["automatic"],
            time_from,
        )
        ebay_orders = ebay_orders_dict.get("content")

        if not ebay_orders:
            return {"content": []}

        await db.add_orders(user.id, ebay_orders)
        await db.set_last_fetched_date(
            user_ref, "orders", current_time.isoformat(), "ebay"
        )
        await db.set_current_no_orders(
            user_ref,
            ebay.numOrders,
            len(ebay_orders),
            "ebay",
        )

        return {"success": True}
    except Exception as error:
        print("update_ebay_orders() error:", error)
        return {"error": error}


async def fetch_ebay_orders(
    db: FirebaseDB,
    uid: str,
    oauth_token: str,
    limit: int,
    time_from,
):
    # Connect to eBay API
    api = Trading(
        appid=os.getenv("CLIENT_ID"),
        devid=os.getenv("DEV_ID"),
        certid=os.getenv("CLIENT_SECRET"),
        token=oauth_token,
        config_file=None,
    )

    # Set up parameters for the API call
    params = {
        "OrderStatus": "All",
        "CreateTimeFrom": time_from,
        "Pagination": {
            "EntriesPerPage": min(10, limit),
            "PageNumber": 1,
        },
    }

    order_details = []
    error = None

    try:
        # Make the eBay API call using GetOrders
        response = api.execute("GetOrders", params)
        response_dict = response.dict()

        order_array = response_dict.get("OrderArray", {})
        if order_array is None:
            return {"content": order_details, "error": error}

        orders = order_array.get("Order", [])

        for order in orders[::-1]:
            if is_refunded_or_incomplete(order):
                await db.remove_order(uid, order["OrderID"])
                continue

            processed_items = await enrich_order_items(db, uid, oauth_token, order)

            detailed_order_data = merge_enriched_data_with_order(processed_items, order)

            order_details.extend(detailed_order_data)

    except Exception as e:
        error = e

    finally:
        return {"content": order_details, "error": error}


def is_refunded_or_incomplete(order):
    # Check if the item has been refunded or the order is not completed
    refunds = order.get("MonetaryDetails", {}).get("Refunds")
    if (refunds is not None) or (order["OrderStatus"] != "Completed"):
        # Skip further processing for incomplete orders
        return True
    return False


async def enrich_order_items(db: FirebaseDB, uid: str, oauth_token: str, order):
    # This list will contain the main details for each order, excluding data such as
    # image, purchasePlatform, purchaseDate etc.
    enriched_items_list = []

    try:

        transactions = order.get("TransactionArray", {}).get("Transaction", [])
        if not transactions:
            return []

        for transaction in transactions:
            item_id = transaction["Item"]["ItemID"]

            # Retrieve listing details from Firebase by item ID
            listing_res = await db.get_listing(uid, item_id)
            listing_data = listing_res.get("listing")
            if not listing_data:
                # If listing data is missing, make an API call to get the item details
                listing_data = fetch_listing_details_from_ebay(item_id, oauth_token)
            else:
                await db.remove_listing(uid, item_id)

            quantity_sold = int(transaction["QuantityPurchased"])
            # Prepare transaction data with additional listing details if available
            enriched_item_data = {
                "orderId": order["OrderID"],
                "legacyItemId": item_id,
                "itemName": transaction["Item"]["Title"],
                "quantitySold": quantity_sold,
                "saleDate": order["CreatedTime"],
                "salePrice": quantity_sold
                * float(transaction["TransactionPrice"]["value"]),
                "recordType": "automatic",
                "salePlatform": transaction["Item"].get("Site", "eBay"),
                "buyerUsername": order["BuyerUserID"],
            }

            # Add image and dateListed from listing data if available
            if listing_data:
                enriched_item_data["image"] = listing_data.get("image")
                enriched_item_data["listingDate"] = listing_data.get("dateListed")
                enriched_item_data["purchaseDate"] = listing_data.get("dateListed")

            enriched_items_list.append(enriched_item_data)

    except Exception as error:
        print(error)

    finally:
        return enriched_items_list


def merge_enriched_data_with_order(enriched_items_list, order):
    detailed_order_data = []

    try:
        # Total sale price (sum of item prices)
        total_sale_price = float(order["AmountPaid"]["value"])

        # Calculate shipping fees
        shipping_cost = calculate_shipping_cost(order)

        # Aggregate order details including item-level details
        for enriched_item in enriched_items_list:
            detailed_order_data.append(
                {
                    **enriched_item,
                    "salePrice": enriched_item["salePrice"],
                    "shippingFees": shipping_cost,
                    "additionalFees": round(
                        total_sale_price - enriched_item["salePrice"] - shipping_cost, 2
                    ),
                    "purchasePrice": None,
                    "purchasePlatform": None,
                }
            )

    except Exception as error:
        print(error)

    finally:
        return detailed_order_data


def calculate_shipping_cost(order):
    shipping_service_options = order["ShippingDetails"].get(
        "ShippingServiceOptions", {}
    )
    shipping_fees = 0
    try:
        # Handle if the shipping fees are stored in a list
        # This can occur if eBay has to authenticate an item
        if isinstance(shipping_service_options, list):
            if shipping_service_options[0].get("ShippingServiceCost") is not None:
                shipping_fees = float(
                    shipping_service_options[0]["ShippingServiceCost"]["value"]
                )
        # Handle if the shipping fees are stored in a dict
        else:
            if shipping_service_options.get("ShippingServiceCost") is not None:
                shipping_fees = float(
                    shipping_service_options["ShippingServiceCost"]["value"]
                )

    except Exception as error:
        print(error)

    finally:
        return shipping_fees
