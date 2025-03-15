from src.db_firebase import FirebaseDB

from google.cloud.firestore_v1 import DocumentReference, DocumentSnapshot
from datetime import datetime, timedelta, timezone
from ebaysdk.trading import Connection as Trading
from ebaysdk.exception import ConnectionError
from dotenv import load_dotenv

import requests
import base64
import os


load_dotenv()


def refresh_ebay_token_direct(firebase_db: FirebaseDB, user_ref: DocumentReference, user_snapshot: DocumentSnapshot):
    """
    Refresh the eBay access token directly without needing to be called from a route.
    This function assumes the user's Firebase data has a valid refresh token stored.
    """
    # Get the eBay account data
    ebay_account_data = user_snapshot.get("connectedAccounts").get("ebay")
    if not ebay_account_data:
        return {"error": "eBay account not connected"}, 400
    
    # Fetch the refresh token
    refresh_token = ebay_account_data.get("ebayRefreshToken")
    if not refresh_token:
        return {"error": "Refresh token not found"}, 400

    try:
        # Refresh the eBay access token using the refresh token
        token_data = refresh_ebay_access_token(refresh_token, os.getenv("CLIENT_ID"), os.getenv("CLIENT_SECRET"))  
        # Store the new token and expiry date in the database
        firebase_db.update_user_token(user_ref, token_data)

        # Return the new access token in the response
        return {"access_token": token_data.get("access_token")}, 200

    except Exception as e:
        return {"error": str(e)}, 500
    

def refresh_ebay_access_token(refresh_token, client_id, client_secret):
    url = "https://api.ebay.com/identity/v1/oauth2/token"

    # Base64 encode the client_id and client_secret
    credentials = f"{client_id}:{client_secret}"
    encoded_credentials = base64.b64encode(credentials.encode("utf-8")).decode("utf-8")

    # Set the authorization header and content-type
    headers = {
        "Authorization": f"Basic {encoded_credentials}",
        "Content-Type": "application/x-www-form-urlencoded"
    }

    # Set the request data (the refresh token and grant type)
    data = {
        'grant_type': 'refresh_token',
        'refresh_token': refresh_token
    }

    # Make the POST request to eBay's token endpoint
    response = requests.post(url, headers=headers, data=data)

    if response.status_code == 200:
        return response.json()  # Successful response with the new access token
    else:
        raise Exception(f"Error refreshing eBay token: {response.status_code}, {response.text}")


def fetch_listings(oauth_token, limit, offset, time_from):
    # Connect to eBay API
    api = Trading(
        appid=os.getenv("CLIENT_ID"),
        devid=os.getenv("DEV_ID"),
        certid=os.getenv("CLIENT_SECRET"),
        token=oauth_token,
        config_file=None,
    )
    print(api)

    # Set up parameters for the API call
    params = {
        "ActiveList": {
            "Include": True,
            "Sort": "TimeLeft",  # Sort listings by time remaining
            "StartTimeFrom": time_from,  # Only fetch listings created after this date
            "Pagination": {
                "EntriesPerPage": min(10, limit),  # Limit the number of listings
                "PageNumber": offset+1,  # Pagination using offset (page number)
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
                "price": round(float(item["SellingStatus"]["CurrentPrice"]["value"]), 2),
                "image": item["PictureDetails"]["GalleryURL"],
                "dateListed": item["ListingDetails"]["StartTime"],
                "listingType": "automatic",
                "quantity": item["QuantityAvailable"] if "QuantityAvailable" in item else 0,
            }
            listings.append(listing_data)

        return listings

    except ConnectionError as e:
        print(f"Error fetching listings: {e}")
        return []


def calc_ebay_time_from(user_ref: DocumentReference, time_from, listing_type):
    # Calculate 90 days ago from the current time in UTC
    ninety_days_ago = datetime.now(timezone.utc) - timedelta(days=90)

    # If the user has not specified the time they want to fetch data from
    if time_from is None:
        # Fetch the last time that eBay was queried
        last_fetched_date = user_ref.get("lastFetchedDate")

        # If no param was given and there's no record of the last listings fetched
        # then default to 90 days ago
        if (last_fetched_date is None):
            return ninety_days_ago.isoformat()
        elif last_fetched_date.get("ebay") is None:
            return ninety_days_ago.isoformat()
        elif last_fetched_date.get("ebay").get(listing_type) is None:
            return ninety_days_ago.isoformat()
        
        # If no param was given but there is a record, then only fetch listings after the last_fetched_date
        return last_fetched_date.get("ebay").get(listing_type)
    
    # If time_from is specified but is more than 90 days ago, adjust it to 90 days ago
    time_from_date = datetime.fromisoformat(time_from)

    # Make sure time_from_date is timezone-aware in UTC
    if time_from_date.tzinfo is None:
        time_from_date = time_from_date.replace(tzinfo=timezone.utc)
    
    if time_from_date < ninety_days_ago:
        return ninety_days_ago.isoformat()
    
    # If time_from is within the last 90 days, return it as is
    return time_from


def fetch_listing_details_from_ebay(item_id, oauth_token):
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