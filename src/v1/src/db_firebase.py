# Local Imports
from .utils import get_next_month_reset_date, format_date_to_iso
from .models import EbayTokenData, StoreType, INumOrders, ItemType, IdKey

# External Imports
from google.cloud.firestore_v1.async_client import AsyncClient
from google.cloud.firestore_v1 import AsyncDocumentReference, FieldFilter
from google.oauth2 import service_account
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

import traceback
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
    async def set_offset(
        self,
        user_ref: AsyncDocumentReference,
        data_type: str,
        date: str,
        store_type: StoreType,
    ):
        """Set offset for inventory or orders."""
        await user_ref.update({f"store.{store_type}.offset.{data_type}": date})

    @handle_firestore_errors
    async def set_current_no_listings(
        self,
        user_ref: AsyncDocumentReference,
        automatic_count: int,
        new_listings: int,
        manual_count: int,
    ):
        """Set the current number of inventory for a user."""
        await user_ref.update(
            {
                f"store.numListings": {
                    "automatic": automatic_count + new_listings,
                    "manual": manual_count,
                }
            }
        )

    @handle_firestore_errors
    async def set_current_no_orders(
        self,
        user_ref: AsyncDocumentReference,
        numOrders: INumOrders,
        new_orders: int,
        new_older_orders: int,
    ):
        """Set the current number of orders for a user, including the totals."""
        # Update the database with the new counts and totals
        current_auto = numOrders.automatic or 0
        current_manual = numOrders.manual or 0
        total_auto = numOrders.totalAutomatic or 0
        total_manual = numOrders.totalManual or 0
        reset_date = numOrders.resetDate or format_date_to_iso(get_next_month_reset_date())

        await user_ref.update(
            {
                f"store.numOrders": {
                    "resetDate": reset_date,
                    "automatic": current_auto + new_orders,
                    "manual": current_manual,
                    "totalAutomatic": total_auto + new_orders + new_older_orders,
                    "totalManual": total_manual,
                }
            }
        )

    @handle_firestore_errors
    async def reset_current_no_orders(
        self,
        user_ref: AsyncDocumentReference,
    ):
        """Reset the current order counts and set a new resetDate."""
        new_reset = format_date_to_iso(get_next_month_reset_date())
        await user_ref.update(
            {
                # Only reset the `resetDate`, `automatic`, and `manual` fields
                f"store.numOrders.resetDate": new_reset,
                f"store.numOrders.automatic": 0,
                f"store.numOrders.manual": 0,
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
            await user_ref.update(
                {f"store.numOrders": updated_numOrders.model_dump()}
            )
            return {
                "success": True,
                "message": "Reset date updated and counts cleared",
                "available": user_limits["automatic"],
            }

        except Exception as error:
            print(traceback.format_exc())
            return {"success": False, "error": str(error)}

    @handle_firestore_errors
    async def retrieve_item(
        self, uid: str, item_id: str, item_type: ItemType, store_type: StoreType
    ):
        """
        Retrieve a specific item for a user from the orders sub-collection.
        """
        try:
            db: AsyncClient = await self.get_db_client()
            # Reference to the specific item document
            ref = (
                db.collection(item_type)
                .document(uid)
                .collection(store_type)
                .document(item_id)
            )

            snapshot = await ref.get()

            # Check if the item exists
            if not snapshot.exists:
                return {"item": None, "error": f"{item_type.capitalize()} not found"}

            # Return the order data
            return {"item": snapshot.to_dict(), "error": None}

        except Exception as error:
            return {"item": None, "error": str(error)}

    @handle_firestore_errors
    async def add_items(
        self, uid: str, items: list, item_type: ItemType, store_type: StoreType
    ):
        """
        Add items as individual documents in the <store_type> sub-collection.
        """
        db: AsyncClient = await self.get_db_client()
        col_ref: AsyncDocumentReference = (
            db.collection(item_type).document(uid).collection(store_type)
        )

        try:
            # Iterate through the items and add them as individual documents
            for item in items:
                doc_id = item.get("id")

                if doc_id:
                    # Add or update the <store_type> in the sub-collection
                    await col_ref.document(doc_id).set(item)

            return {"success": True, "message": f"{item_type}s added successfully"}

        except Exception as error:
            print(traceback.format_exc())
            return {"success": False, "message": str(error)}

    @handle_firestore_errors
    async def remove_item(self, uid: str, item_id: str, item_type: ItemType, store_type: StoreType):
        """
        Remove a specific item from the orders sub-collection.
        """
        try:
            db: AsyncClient = await self.get_db_client()
            # Reference to the specific order document
            ref: AsyncDocumentReference = (
                db.collection(item_type)
                .document(uid)
                .collection(store_type)
                .document(item_id)
            )

            snapshot = await ref.get()

            # Check if the item exists before trying to delete
            if not snapshot.exists:
                return {"success": False, "message": f"{item_type.capitalize()} not found"}

            # Delete the item document
            await ref.delete()
            return {
                "success": True,
                "message": f"{item_type.capitalize()} removed successfully",
            }

        except Exception as error:
            return {"success": False, "message": str(error)}

    @handle_firestore_errors
    async def get_items_by_ids(
        self,
        uid: str,
        item_ids: list[str],
        item_type: ItemType,
        store: StoreType,
        id_key: IdKey,
    ) -> dict:
        """
        Retrieve multiple items for a user from the <item_type> sub-collection
        using an 'in' query on the 'IdKey' field.

        Note: Firestore's 'in' query supports a maximum of 10 values. If item_ids exceeds
        this, the query must be run in batches.

        Args:
            uid (str): The user ID.
            item_ids (list[str]): A list of item IDs for which to fetch items.
        """
        try:
            db: AsyncClient = await self.get_db_client()
            ref = db.collection(item_type).document(uid).collection(store)

            item_map = {}

            # Batch the item_ids into chunks of 10
            batch_size = 10
            for i in range(0, len(item_ids), batch_size):
                batch_item_ids = item_ids[i : i + batch_size]
                query = ref.where(filter=FieldFilter(id_key, "in", batch_item_ids))
                docs = await query.get()
                for doc in docs:
                    data = doc.to_dict()
                    item_id = data.get(id_key)
                    if item_id:
                        item_map[item_id] = data

            return item_map

        except Exception as error:
            print(traceback.format_exc())
            raise error
