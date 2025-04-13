# Local Imports
from ..ebay.db_firebase import FirebaseDB, get_db
from ..models import EbayTokenData, RefreshEbayTokenData, IEbay, IUser

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


# Fetch and authenticate a user based on the provided request.
async def fetch_user_and_update_tokens(
    request: Request,
) -> tuple[AsyncDocumentReference, DocumentSnapshot, IUser] | HTTPException:
    try:
        uid = request.query_params.get("uid")
        auth_header = request.headers.get("Authorization")

        token = None
        # Check if the header is present and starts with "Bearer"
        if auth_header and auth_header.startswith("Bearer "):
            # Extract the token after "Bearer "
            token = auth_header.split(" ")[1]
        else:
            return HTTPException(
                status_code=401, detail="Unauthorized: No valid token provided"
            )

        # Fetch the user from the database
        db = get_db()
        user_ref = await db.query_user_ref(uid)
        user_snapshot = await user_ref.get()
        user_doc = user_snapshot.to_dict()

        if not user_doc:
            return HTTPException(status_code=404, detail="User not found")

        user = IUser(**user_doc)

        # Check if the user has connected their eBay account
        connected_accounts = user.connectedAccounts
        ebay_account = connected_accounts.ebay
        if not ebay_account:
            return HTTPException(
                status_code=401, detail="Unauthorized: eBay account not connected"
            )

        # Confirm the give access token is the same as the one stored in the database
        if ebay_account.ebayAccessToken != token:
            return HTTPException(
                status_code=401, detail="Unauthorized: Invalid token provided"
            )

        token_update_result = await check_and_refresh_ebay_token(
            db, user_ref, ebay_account
        )
        if not token_update_result.get("success"):
            return HTTPException(
                status_code=401,
                detail=f"Unauthorized: Token refresh failed. {token_update_result.get('error')}",
            )

        token_data: EbayTokenData | None = token_update_result.get("token_data")
        if token_data is not None:
            user.connectedAccounts.ebay.ebayAccessToken = token_data.access_token
            user.connectedAccounts.ebay.ebayRefreshToken = token_data.refresh_token

            # Get the current time and calculate the expiration timestamp
            current_time = datetime.now(timezone.utc)
            expiry_time = current_time + timedelta(seconds=token_data.expires_in)
            expiry_timestamp = int(
                expiry_time.timestamp()

            )  # Convert to Unix timestamp in seconds
            user.connectedAccounts.ebay.ebayTokenExpiry = expiry_timestamp

    except Exception as error:
        print("Error in fetch_user_and_update_tokens()", error)
        print(traceback.format_exc())
        return HTTPException(status_code=500, detail=str)

    return user_ref, user_snapshot, user


async def check_and_refresh_ebay_token(
    db: FirebaseDB, user_ref: AsyncDocumentReference, ebay_account: IEbay
):
    """
    Refresh the eBay access token directly without needing to be called from a route.
    This function assumes the user's Firebase data has a valid refresh token stored.
    """
    try:
        # Check if the users eBay token has expired
        token_expiry = ebay_account.ebayTokenExpiry
        refresh_token = ebay_account.ebayRefreshToken
        current_timestamp = int(datetime.now(timezone.utc).timestamp())

        if len(str(token_expiry)) > 10:  # Check if it's in milliseconds
            token_expiry = int(token_expiry) // 1000  # Convert ms to seconds

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

        return {"success": True, "token_data": token_data.data}
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
