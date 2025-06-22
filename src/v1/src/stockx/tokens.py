# Local Imports
from ..models import EbayTokenData, RefreshEbayTokenData, IUser
from ..db_firebase import FirebaseDB, get_db

# External Imports
from google.cloud.firestore_v1 import AsyncDocumentReference
from datetime import datetime, timezone, timedelta
from fastapi import HTTPException, Request
from typing import Dict, Any

import traceback
import httpx
import os


# --------------------------------------------------- #
# StockX Token Refresh                                  #
# --------------------------------------------------- #


async def check_and_refresh_stock_token(
    db: FirebaseDB, user_ref: AsyncDocumentReference, user: IUser
):
    """
    Refresh the StockX access token directly without needing to be called from a route.
    This function assumes the user's Firebase data has a valid refresh token stored.
    """
    account = user.connectedAccounts.stockx

    try:
        # Step 3: Check if the token is store as milliseconds (If true convert to seconds)
        if len(str(account.stockxTokenExpiry)) > 10:
            account.stockxTokenExpiry = (
                int(account.stockxTokenExpiry) // 1000
            )  # Convert ms to seconds

        # Step 4: Check if the users stockx token has expired
        current_time = datetime.now(timezone.utc)
        current_timestamp = int(current_time.timestamp())
        if account.stockxTokenExpiry > current_timestamp:
            return {"success": True, "user": user}

        # Step 5: Refresh the stockx access token using the refresh token
        token_data = await refresh_stockx_access_token(account.stockxRefreshToken)
        if token_data.get("error"):
            return {"success": False, "error": token_data.get("error")}

        # Step 6: Store the new token and expiry date in the database
        await db.update_user_token(user_ref, token_data)

        # Step 7: Get the current time and calculate the expiration timestamp
        expiry_time = current_time + timedelta(seconds=token_data.data.expires_in)
        expiry_timestamp = int(expiry_time.timestamp())  # Convert to Unix timestamp in seconds

        # Step 8: Update user token data
        user.connectedAccounts.stockx.stockxAccessToken = token_data.data.access_token
        user.connectedAccounts.stockx.stockxTokenExpiry = token_data.data.refresh_token
        user.connectedAccounts.stockx.stockxTokenExpiry = expiry_timestamp

        return {"success": True, "user": user}
    except Exception as e:
        print(traceback.format_exc())
        return {"success": False, "error": f"check_and_refresh_stockx_token(): {str(e)}"}


async def refresh_stockx_access_token(refresh_token: str) -> Dict[str, Any]:
    CLIENT_ID = os.getenv("STOCKX_CLIENT_ID")
    CLIENT_SECRET = os.getenv("STOCKX_CLIENT_SECRET")
    REDIRECT_URI = os.getenv("STOCKX_REDIRECT_URI")

    try:
        if not CLIENT_ID or not CLIENT_SECRET or not REDIRECT_URI:
            raise Exception("Missing client credentials.")

        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://accounts.stockx.com/oauth/token",
                headers={"Content-Type": "application/json"},
                json={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "client_id": CLIENT_ID,
                    "client_secret": CLIENT_SECRET,
                    "audience": "gateway.stockx.com"
                }
            )

        if response.status_code != 200:
            error_data = response.json()
            raise Exception(error_data.get("error", "Unknown error"))

        token_data = response.json()
        return RefreshEbayTokenData(
            data=EbayTokenData(
                access_token=token_data.get("access_token", ""),
                expires_in=token_data.get("expires_in", 0),
                refresh_token=refresh_token,
            ),
            error=None,
        )

    except Exception as error:
        print("Error refreshing StockX token:", str(error))
        return RefreshEbayTokenData(
            data=None,
            error=f"refresh_stockx_access_token(): {str(error)}",
        )