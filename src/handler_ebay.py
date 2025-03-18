# Local Imports
from src.db_firebase import FirebaseDB
from src.models import EbayTokenData, SuccessOrError, RefreshEbayTokenData, IEbay

# External Imports
from google.cloud.firestore_v1 import AsyncDocumentReference
from ebaysdk.exception import ConnectionError
from ebaysdk.trading import Connection as Trading
from datetime import datetime, timezone
from dotenv import load_dotenv

import requests
import base64
import os


load_dotenv()


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


def fetch_listings(oauth_token: str, limit: int, time_from):
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
                "PageNumber": 1, 
            },
        }
    }

    try:
        # Make the eBay API call using GetMyeBaySelling
        response = api.execute("GetMyeBaySelling", params)
        response_dict = response.dict()

        # Parse the response and extract the necessary listing data
        listings = []

        items = response_dict.get("ActiveList", {}).get("ItemArray", {}).get("Item", [])
        for item in items:
            listing_data = {
                "itemId": item["ItemID"],
                "itemName": item["Title"],
                "price": round(
                    float(item["SellingStatus"]["CurrentPrice"]["value"]), 2
                ),
                "image": item["PictureDetails"]["GalleryURL"],
                "dateListed": item["ListingDetails"]["StartTime"],
                "listingType": "automatic",
                "quantity": (
                    item["QuantityAvailable"] if "QuantityAvailable" in item else 0
                ),
            }
            listings.append(listing_data)

        return listings

    except ConnectionError as e:
        print(f"Error fetching listings: {e}")
        return []


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