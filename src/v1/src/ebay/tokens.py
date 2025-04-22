# Local Imports
from ..models import EbayTokenData, RefreshEbayTokenData, IEbay, IUser
from ..db_firebase import FirebaseDB, get_db

# External Imports
from google.cloud.firestore_v1 import AsyncDocumentReference, DocumentSnapshot
from datetime import datetime, timezone, timedelta
from fastapi import HTTPException, Request

import traceback
import requests
import base64
import os


# --------------------------------------------------- #
# eBay Token Refresh                                  #
# --------------------------------------------------- #


async def check_and_refresh_ebay_token(
    request: Request, db: FirebaseDB, user_ref: AsyncDocumentReference, user: IUser
):
    """
    Refresh the eBay access token directly without needing to be called from a route.
    This function assumes the user's Firebase data has a valid refresh token stored.
    """
    token = None
    account = user.connectedAccounts.ebay

    try:
        # Step 1: Check if the user provided an Autorization header
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ")[1]
        else:
            return HTTPException(
                status_code=401, detail="Unauthorized: No valid token provided"
            )

        # Step 2: Check access token is the same as the one stored in the database
        if account.ebayAccessToken != token:
            return HTTPException(
                status_code=401, detail="Unauthorized: Invalid token provided"
            )

        # Step 3: Check if the token is store as milliseconds (If true convert to seconds)
        if len(str(account.ebayTokenExpiry)) > 10:
            account.ebayTokenExpiry = (
                int(account.ebayTokenExpiry) // 1000
            )  # Convert ms to seconds

        # Step 4: Check if the users eBay token has expired
        current_time = datetime.now(timezone.utc)
        current_timestamp = int(current_time.timestamp())
        if account.ebayTokenExpiry > current_timestamp:
            return {"success": True, "user": user}

        # Step 5: Refresh the eBay access token using the refresh token
        token_data = await refresh_ebay_access_token(
            account.ebayRefreshToken, os.getenv("CLIENT_ID"), os.getenv("CLIENT_SECRET")
        )
        if token_data.data is None:
            return {"success": False, "error": token_data.error}

        # Step 6: Store the new token and expiry date in the database
        await db.update_user_token(user_ref, token_data.data)

        # Step 7: Get the current time and calculate the expiration timestamp
        expiry_time = current_time + timedelta(seconds=token_data.data.expires_in)
        expiry_timestamp = int(expiry_time.timestamp())  # Convert to Unix timestamp in seconds

        # Step 8: Update user token data
        user.connectedAccounts.ebay.ebayAccessToken = token_data.data.access_token
        user.connectedAccounts.ebay.ebayRefreshToken = token_data.data.refresh_token
        user.connectedAccounts.ebay.ebayTokenExpiry = expiry_timestamp

        return {"success": True, "user": user}
    except Exception as e:
        print(traceback.format_exc())
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
