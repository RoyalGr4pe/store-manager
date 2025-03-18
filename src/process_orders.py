# Local Imports
from src.db_firebase import FirebaseDB
from src.handler_ebay import fetch_listing_details_from_ebay

# External Imports
from ebaysdk.trading import Connection as Trading

import os


async def fetch_orders(
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
        }
    }

    order_details = []
    error = None

    try:
        # Make the eBay API call using GetOrders
        response = api.execute("GetOrders", params)
        response_dict = response.dict()

        order_array = response_dict.get("OrderArray", {})
        if order_array is None:
            return { "content": order_details, "error": error }

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
        return { "content": order_details, "error": error }


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
                "salePrice": quantity_sold*float(transaction["TransactionPrice"]["value"]),
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
                    "additionalFees": round(total_sale_price - enriched_item["salePrice"] - shipping_cost, 2),
                    "purchasePrice": None,
                    "purchasePlatform": None,
                }
            )

    except Exception as error:
        print(error)

    finally:
        return detailed_order_data


def calculate_shipping_cost(order):
    shipping_service_options = order["ShippingDetails"].get("ShippingServiceOptions", {})
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