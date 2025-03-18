# External Imports
from ebaysdk.exception import ConnectionError
from ebaysdk.trading import Connection as Trading
from datetime import datetime
from dotenv import load_dotenv

import os


load_dotenv()


def fetch_listings(oauth_token, limit, time_from):
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

            quantity = int(item["QuantityAvailable"]) if "QuantityAvailable" in item else 0
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
        return { "content": listings, "error": error }
