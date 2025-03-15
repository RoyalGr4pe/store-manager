from .handler_limits import calc_user_set_limit
from .handler_ebay import calc_ebay_time_from

from datetime import datetime, timedelta, timezone
from ebaysdk.trading import Connection as Trading
from ebaysdk.exception import ConnectionError
from dotenv import load_dotenv
from math import ceil

import os


load_dotenv()



def fetch_listings(oauth_token, limit, offset, time_from):
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

    page_no = ceil(offset / 10)
    page_offset = offset - ((page_no-1) * 10)
    # Set up parameters for the API call
    params = {
        "ActiveList": {
            "Include": True,
            "Sort": "TimeLeft",  # Sort listings by time remaining
            "StartTimeFrom": time_from,  # Only fetch listings created after this date
            "Pagination": {
                "EntriesPerPage": min(10, limit),  # Limit the number of listings
                "PageNumber": page_no,  # Pagination using offset (page number)
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
        for item in items[page_offset-1:]:
            # Get the date the item was listed
            date_listed = item["ListingDetails"]["StartTime"]
            # Convert the date_listed from string to datetime object
            date_listed_obj = datetime.fromisoformat(date_listed)

            quantity = item["QuantityAvailable"] if "QuantityAvailable" in item else 0
            if int(quantity) == 0:
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
                    "quantity": int(quantity),
                }
                listings.append(listing_data)

        
    except ConnectionError as e:
        error = e
    
    finally:
        return { "content": listings, "error": error }



def set_listing_query_params(request, user_ref, user_limits):
    params = {}

    subscription_max_listings = user_limits["automatic"] + user_limits["manual"]
    user_set_limit = int(request.args.get("limit", subscription_max_listings))
    time_from = request.args.get("time_from")

    params["limit"] = calc_user_set_limit(user_set_limit, subscription_max_listings)
    params["offset"] = int(request.args.get("offset", 1))
    params["subscription_max_listings"] = subscription_max_listings
    params["max_listings_automatic"] = user_limits["automatic"]
    params["max_listings_manual"] = user_limits["manual"]
    params["db_time_from"] = time_from
    params["ebay_time_from"] = calc_ebay_time_from(
        user_ref, time_from, "listings"
    )

    return params

