# Local Imports
from ..utils import get_next_month_reset_date, format_date_to_iso
from ..models import EbayTokenData, StoreType, INumOrders

# External Imports
from google.cloud.firestore_v1.async_client import AsyncClient
from google.cloud.firestore_v1.collection import CollectionReference
from google.cloud.firestore_v1 import AsyncDocumentReference, FieldFilter
from google.oauth2 import service_account
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

import os

load_dotenv()


# Connect to Firebase
db = None

def get_db():
    global db
    if not db:
        db = FirebaseDB()
    return db


def handle_firestore_errors(func):
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            # Print the function name along with the error
            print(f"{func.__name__} | Firebase Error: {e}")
            raise RuntimeError("An error occurred while interacting with Firebase.")

    return wrapper


class FirebaseDB:
    # Class-level attributes for environment variables
    FIREBASE_PROJECT_ID = os.getenv("FIREBASE_PROJECT_ID")
    FIREBASE_PRIVATE_KEY_ID = os.getenv("FIREBASE_PRIVATE_KEY_ID")
    FIREBASE_PRIVATE_KEY = os.getenv("FIREBASE_PRIVATE_KEY").replace("\\n", "\n")
    FIREBASE_CLIENT_EMAIL = os.getenv("FIREBASE_CLIENT_EMAIL")
    FIREBASE_CLIENT_ID = os.getenv("FIREBASE_CLIENT_ID")
    FIREBASE_CLIENT_X509_CERT_URL = os.getenv("FIREBASE_CLIENT_X509_CERT_URL")
    FIREBASE_PROJECT_URL = os.getenv("FIREBASE_PROJECT_URL")

    # A flag to track initialization
    _initialized = False
    _firebase_credentials = None

    def __init__(self) -> None:
        if not FirebaseDB._initialized:
            # Credentials for service account
            FirebaseDB._firebase_credentials = service_account.Credentials.from_service_account_info(
                {
                    "type": "service_account",
                    "project_id": FirebaseDB.FIREBASE_PROJECT_ID,
                    "private_key_id": FirebaseDB.FIREBASE_PRIVATE_KEY_ID,
                    "private_key": FirebaseDB.FIREBASE_PRIVATE_KEY,
                    "client_email": FirebaseDB.FIREBASE_CLIENT_EMAIL,
                    "client_id": FirebaseDB.FIREBASE_CLIENT_ID,
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
                    "client_x509_cert_url": FirebaseDB.FIREBASE_CLIENT_X509_CERT_URL,
                    "universe_domain": "googleapis.com",
                }
            )

            # Mark as initialized
            FirebaseDB._initialized = True

    async def get_db_client(self) -> AsyncClient:
        return AsyncClient(
            project=FirebaseDB.FIREBASE_PROJECT_ID,
            credentials=FirebaseDB._firebase_credentials,
        )

    async def query_user_ref(self, uid: str) -> AsyncDocumentReference:
        """
        Retrieve a user reference by uid.
        """
        db: AsyncClient = await self.get_db_client()
        return db.collection("users").document(uid)

    @handle_firestore_errors
    async def update_user_token(
        self, user_ref: AsyncDocumentReference, token_data: EbayTokenData
    ):
        """
        Update the eBay access token and its expiry for a specific user identified by uid.
        """
        new_access_token = token_data.access_token
        expires_in = token_data.expires_in  # Time in seconds

        if not user_ref or not new_access_token or expires_in is None:
            return {
                "success": False,
                "message": "Invalid parameters: uid, new_access_token, and expires_in are required",
            }

        try:
            # Get the current time and calculate the expiration timestamp
            current_time = datetime.now(timezone.utc)
            expiry_time = current_time + timedelta(seconds=expires_in)
            expiry_timestamp = int(
                expiry_time.timestamp()
            )  # Convert to Unix timestamp in seconds

            await user_ref.update(
                {
                    "connectedAccounts.ebay.ebayAccessToken": new_access_token,
                    "connectedAccounts.ebay.ebayTokenExpiry": expiry_timestamp,
                }
            )

            return {"success": True, "message": "Token and expiry updated successfully"}
        except Exception as e:
            return {"success": False, "message": str(e)}

    @handle_firestore_errors
    async def set_last_fetched_date(
        self,
        user_ref: AsyncDocumentReference,
        data_type: str,
        date: str,
        store_type: StoreType,
    ):
        """Set the last fetched date for inventory or orders."""
        await user_ref.update({f"store.{store_type}.lastFetchedDate.{data_type}": date})

    @handle_firestore_errors
    async def set_current_no_listings(
        self,
        user_ref: AsyncDocumentReference,
        automatic_count: int,
        new_listings: int,
        manual_count: int,
        store_type: StoreType,
    ):
        """Set the current number of inventory for a user."""
        await user_ref.update(
            {
                f"store.{store_type}.numListings": {
                    "automatic": automatic_count + new_listings,
                    "manual": manual_count,
                }
            }
        )

    @handle_firestore_errors
    async def check_and_reset_automatic_date(
        self, user_ref: AsyncDocumentReference, numOrders: INumOrders, user_limits: dict
    ):
        try:            
            # Ensure resetDate exists; otherwise, set an initial resetDate
            if not numOrders.resetDate:
                new_reset_date = format_date_to_iso(get_next_month_reset_date())
            else:
                # Get the reset date from the document (remove any trailing "Z" if present)
                reset_date_str = numOrders.resetDate
                reset_date = datetime.fromisoformat(reset_date_str.replace("Z", "")).date()
                current_date = datetime.now(timezone.utc).date()

                if current_date >= reset_date:
                    # Time to reset the counts
                    new_reset_date = format_date_to_iso(get_next_month_reset_date())
                else:
                    if numOrders.automatic >= user_limits["automatic"]:
                        return {"success": False, "message": "You have hit your limit for automatically fetching orders"}
                    # No reset necessary and user is below limit
                    return {
                        "success": True,
                        "message": "Reset not required",
                        "available": user_limits["automatic"] - numOrders.automatic,
                    }

            # Create an updated orders structure with counts reset to zero.
            updated_numOrders = numOrders.model_copy()
            updated_numOrders.automatic = 0
            updated_numOrders.manual = 0
            updated_numOrders.resetDate = new_reset_date

            # Update the document. Adjust field path if your structure is different.
            await user_ref.update({"store.ebay.numOrders": updated_numOrders.model_dump()})
            return {
                "success": True,
                "message": "Reset date updated and counts cleared",
                "available": user_limits["automatic"],
            }

        except Exception as error:
            print("Error in check_and_reset_automatic_date:", error)
            return {"success": False, "error": str(error)}

    @handle_firestore_errors
    async def set_current_no_orders(
        self,
        user_ref: AsyncDocumentReference,
        numOrders: INumOrders,
        new_orders: int,
        new_older_orders: int,
        store_type: StoreType,
    ):
        """Set the current number of orders for a user, including the totals."""
        if numOrders.automatic == 0 and new_orders == -1:
            return {"success": True}

        try:
            # Get current date in UTC and parse resetDate correctly
            current_date = datetime.now(timezone.utc).date()
            reset_date = datetime.fromisoformat(
                numOrders.resetDate.replace("Z", "")
            ).date()

            # Check if current date is greater than or equal to resetDate
            if current_date >= reset_date:
                # Reset automatic and manual to zero
                automatic_count = new_orders
                manual_count = 0

                # Set resetDate to the 1st day of the next month
                next_month_date = format_date_to_iso(get_next_month_reset_date())
            else:
                # Increment counts as usual
                automatic_count = numOrders.automatic + new_orders
                manual_count = numOrders.manual
                next_month_date = numOrders.resetDate

            print("Manual Count", manual_count)
            print()

            return {"success": True}
            # Update the database with the new counts and totals
            await user_ref.update(
                {
                    f"store.{store_type}.numOrders": {
                        "resetDate": next_month_date,
                        "automatic": automatic_count,
                        "manual": manual_count,
                        "totalAutomatic": numOrders.totalAutomatic
                        + new_orders
                        + new_older_orders,
                        "totalManual": numOrders.totalManual,
                    }
                }
            )
            return {"success": True}

        except Exception as error:
            print(f"Error in set_current_no_orders: {error}")
            return {"error": str(error)}

    @handle_firestore_errors
    async def get_listing(self, uid: str, listing_id: str):
        """
        Retrieve a specific listing for a user from the listings sub-collection.
        """
        try:
            db: AsyncClient = await self.get_db_client()
            # Reference to the specific listing document
            listing_ref = (
                db.collection("inventory")
                .document(uid)
                .collection("ebay")
                .document(listing_id)
            )

            listing_snapshot = await listing_ref.get()

            # Check if the listing exists
            if not listing_snapshot.exists:
                return {"listing": None, "error": "Listing not found"}

            # Return the listing data
            return {"listing": listing_snapshot.to_dict(), "error": None}

        except Exception as error:
            return {"listing": None, "error": str(error)}

    @handle_firestore_errors
    async def add_listings(self, uid: str, inventory: list):
        """
        Add listings as individual documents in the inventory sub-collection.
        """
        db: AsyncClient = await self.get_db_client()
        inventory_ref: CollectionReference = (
            db.collection("inventory").document(uid).collection("ebay")
        )

        try:
            # Iterate through the listings and add them as individual documents
            for listing in inventory:
                listing_id = listing.get("itemId")
                if listing_id:
                    if isinstance(listing.get("image"), str):
                        listing["image"] = [listing["image"]]
                    elif not listing.get("image"):
                        listing["image"] = []

                    # Add or update the listing in the sub-collection
                    await inventory_ref.document(listing_id).set(listing)

            return {
                "success": True,
                "message": "Listings added successfully to inventory",
            }

        except Exception as error:
            return {"success": False, "message": str(error)}

    @handle_firestore_errors
    async def remove_listing(self, uid: str, listing_id: str):
        """
        Remove a specific listing from the listings sub-collection.
        """
        try:
            db: AsyncClient = await self.get_db_client()
            # Reference to the specific listing document
            listing_ref = (
                db.collection("inventory")
                .document(uid)
                .collection("listings")
                .document(listing_id)
            )

            await listing_ref.delete()

            return {"success": True, "message": "Listing removed successfully"}

        except Exception as error:
            return {"success": False, "message": str(error)}

    @handle_firestore_errors
    async def get_order(self, uid: str, transaction_id: str):
        """
        Retrieve a specific order for a user from the orders sub-collection.
        """
        try:
            db: AsyncClient = await self.get_db_client()
            # Reference to the specific order document
            order_ref = (
                db.collection("orders")
                .document(uid)
                .collection("ebay")
                .document(transaction_id)
            )

            order_snapshot = await order_ref.get()

            # Check if the order exists
            if not order_snapshot.exists:
                return {"order": None, "error": "Order not found"}

            # Return the order data
            return {"order": order_snapshot.to_dict(), "error": None}

        except Exception as error:
            return {"order": None, "error": str(error)}

    @handle_firestore_errors
    async def add_orders(self, uid: str, orders: list):
        """
        Add orders as individual documents in the orders sub-collection.
        """
        db: AsyncClient = await self.get_db_client()
        orders_ref: AsyncDocumentReference = (
            db.collection("orders").document(uid).collection("ebay")
        )

        try:
            # Iterate through the orders and add them as individual documents
            for order in orders:
                transaction_id = order.get("transactionId")

                if transaction_id:
                    # Ensure the "image" field is always a list
                    if isinstance(order.get("image"), str):
                        order["image"] = [order["image"]]
                    elif not order.get("image"):
                        order["image"] = []

                    # Add or update the order in the sub-collection
                    await orders_ref.document(transaction_id).set(order)

            return {"success": True, "message": "Orders added successfully"}

        except Exception as error:
            return {"success": False, "message": str(error)}

    @handle_firestore_errors
    async def remove_order(self, uid: str, transaction_id: str):
        """
        Remove a specific order from the orders sub-collection.
        """
        try:
            db: AsyncClient = await self.get_db_client()
            # Reference to the specific order document
            order_ref: AsyncDocumentReference = (
                db.collection("orders")
                .document(uid)
                .collection("ebay")
                .document(transaction_id)
            )

            order_snapshot = await order_ref.get()

            # Check if the order exists before trying to delete
            if not order_snapshot.exists:
                return {"success": False, "message": "Order not found"}

            # Delete the order document
            await order_ref.delete()
            return {"success": True, "message": "Order removed successfully"}

        except Exception as error:
            return {"success": False, "message": str(error)}

    @handle_firestore_errors
    async def get_listings_by_ids(self, uid: str, item_ids: list[str]) -> dict:
        """
        Retrieve multiple listings for a user from the inventory sub-collection
        using an 'in' query on the 'itemId' field.

        Note: Firestore's 'in' query supports a maximum of 10 values. If item_ids exceeds
        this, the query must be run in batches.

        Args:
            uid (str): The user ID.
            item_ids (list[str]): A list of item IDs for which to fetch listings.

        Returns:
            dict: A mapping of itemId to its listing data (document data).
                For example: { "387218355644": { ...listing data... }, ... }
        """
        try:
            db: AsyncClient = await self.get_db_client()
            listings_ref = db.collection("inventory").document(uid).collection("ebay")

            listings_map = {}

            # Batch the item_ids into chunks of 10
            batch_size = 10
            for i in range(0, len(item_ids), batch_size):
                batch_item_ids = item_ids[i : i + batch_size]
                query = listings_ref.where(filter=FieldFilter("itemId", "in", batch_item_ids))
                docs = await query.get()
                for doc in docs:
                    data = doc.to_dict()
                    item_id = data.get("itemId")
                    if item_id:
                        listings_map[item_id] = data

            return listings_map

        except Exception as error:
            print("Error in get_listings_by_ids:", error)
            raise error
