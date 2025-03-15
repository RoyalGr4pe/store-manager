from google.cloud.firestore_v1 import DocumentReference, DocumentSnapshot
from firebase_admin import firestore, credentials
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

import firebase_admin
import os

load_dotenv()


def handle_firestore_errors(func):
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
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

    def __init__(self) -> None:
        if not FirebaseDB._initialized:
            # Credentials for service account
            firebase_credentials = credentials.Certificate(
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

            # Firebase options
            firebase_options = {"projectId": FirebaseDB.FIREBASE_PROJECT_ID}

            # Initialize the Firebase Admin SDK
            firebase_admin.initialize_app(firebase_credentials, firebase_options)

            # Mark as initialized
            FirebaseDB._initialized = True

        # Firestore client
        self.db = firestore.client()


    @handle_firestore_errors
    def query_user_ref(self, user_id: str) -> DocumentReference:
        """
        Retrieve a user reference by user_id.
        """
        return self.db.collection("users").document(user_id)


    @handle_firestore_errors
    def update_user_token(self, user_ref: DocumentReference, token_data: dict):
        """
        Update the eBay access token and its expiry for a specific user identified by user_id.
        """
        new_access_token = token_data.get("access_token")
        expires_in = token_data.get("expires_in")  # Time in seconds

        if not user_ref or not new_access_token or expires_in is None:
            return {
                "success": False,
                "message": "Invalid parameters: user_id, new_access_token, and expires_in are required",
            }

        try:
            # Get the current time and calculate the expiration timestamp
            current_time = datetime.now(timezone.utc)
            expiry_time = current_time + timedelta(seconds=expires_in)
            expiry_timestamp = int(expiry_time.timestamp())  # Convert to Unix timestamp in seconds
            
            user_ref.update(
                {
                    "connectedAccounts.ebay.ebayAccessToken": new_access_token,
                    "connectedAccounts.ebay.ebayTokenExpiry": expiry_timestamp  
                }
            )

            return {"success": True, "message": "Token and expiry updated successfully"}
        except Exception as e:
            print(e)
            return {"success": False, "message": str(e)}


    @handle_firestore_errors
    def query_user_subscriptions(self, user_id: str, sub_names=[]):
        """
        Retrieve subscriptions for a user, optionally filtered by subscription names.
        """
        user_ref = self.query_user(user_id)
        if not user_ref:
            return {"subscriptions": [], "error": "User not found"}

        subscriptions = user_ref.get("subscriptions", [])
        if not subscriptions:
            return {"subscriptions": [], "error": "No subscriptions found"}

        if not sub_names:
            return {"subscriptions": subscriptions, "error": None}

        filtered_subscriptions = [
            sub
            for sub in subscriptions
            if any(sub_name.lower() in sub["name"].lower() for sub_name in sub_names)
        ]

        if not filtered_subscriptions:
            return {"subscriptions": [], "error": "No matching subscriptions found"}

        return {"subscriptions": filtered_subscriptions, "error": None}


    @handle_firestore_errors
    def set_last_fetched_date(self, user_ref: DocumentReference, data_type: str, date: str):
        """Set the last fetched date for inventory or orders."""
        user_ref.update({f"lastFetchedDate.ebay.{data_type}": date})

    @handle_firestore_errors
    def set_current_no_listings(
        self, user_ref: DocumentReference, automatic_count: int, manual_count: int
    ):
        """Set the current number of inventory for a user."""
        user_ref.update(
            {"numListings": {"automatic": automatic_count, "manual": manual_count}}
        )


    @handle_firestore_errors
    def set_current_no_orders(
        self, user_ref: DocumentReference, automatic_count: int, manual_count: int
    ):
        """Set the current number of orders for a user."""
        user_ref.update(
            {"numOrders": {"automatic": automatic_count, "manual": manual_count}}
        )


    @handle_firestore_errors
    def add_or_update_orders(self, user_id: str, order: dict):
        """Add or update an eBay order for a user."""
        user_ref = self.db.collection("users").document(user_id)
        user_ref.update({"orders": {"ebay": order}}) @ handle_firestore_errors


    @handle_firestore_errors
    def add_or_update_inventory(self, user_id: str, inventory_item: dict):
        """Add or update an eBay inventory item for a user."""
        user_ref = self.db.collection("users").document(user_id)
        user_ref.update({"inventory": {"ebay": inventory_item}})


    @handle_firestore_errors
    def get_listing(self, user_ref: DocumentReference, listing_id: str):
        """Retrieve a specific listing for a user."""
        inventory = user_ref.get("inventory").get("ebay")
        if not inventory:
            return {"listing": None, "error": "No inventory found"}

        listing = next((item for item in inventory if item["itemId"] == listing_id), None)
        if not listing:
            return {"listing": None, "error": "Listing not found"}

        return {"listing": listing, "error": None}


    @handle_firestore_errors
    def get_listings(self, user_snapshot: DocumentSnapshot, limit: int, offset: int, db_time_from: str):
        """Retrieve inventory for a user."""
        inventory_dict: dict = user_snapshot.get("inventory").get("ebay")
        if not inventory_dict:
            return {"inventory": [], "error": "No inventory found"}

        if db_time_from:
            db_time_from_obj = datetime.fromisoformat(db_time_from)
            
            # Make db_time_from_obj timezone-aware if it's naive
            if db_time_from_obj.tzinfo is None:
                db_time_from_obj = db_time_from_obj.replace(tzinfo=timezone.utc)

            inventory = [
                item
                for _, item in inventory_dict.items()
                if "dateListed" in item and item["dateListed"] is not None
                # Ensure item["dateListed"] is a timezone-aware datetime
                if datetime.fromisoformat(item["dateListed"]).astimezone(timezone.utc) >= db_time_from_obj
            ]

        return {"inventory": inventory[offset - 1 : offset - 1 + limit], "error": None}
    

    @handle_firestore_errors
    def add_listings(self, user_ref: DocumentReference, user_snapshot: DocumentSnapshot, inventory: list):
        # Retrieve the user document snapshot
        inventory_field = user_snapshot.get("inventory").get("ebay")

        # If user document doesn't exist, handle accordingly
        if not inventory_field:
            inventory_field = {}

        try:   
            print(inventory)
            # Iterate through the listings (assuming the structure provided)
            for listing in inventory:
                print(listing)
                listing_id = listing.get("itemId")  # Get the listing ID (ItemID from eBay)
                if listing_id:
                    if (listing.get('image') is None):
                        listing['image'] = []
                    elif isinstance(listing.get('image'), str):
                        listing['image'] = [listing['image']]
      
                    # Store the listing data under the listing_id
                    inventory_field[listing_id] = listing

            # Update the user's document with the modified inventory
            user_ref.update({
                "inventory.ebay": inventory_field
            })

            return {"success": True, "message": "Listings added successfully"}

        except Exception as error:
            print(error)
            return {"success": False, "message": str(error)}

        
    @handle_firestore_errors
    def get_orders(self, user_snapshot: DocumentSnapshot, limit: int, offset: int, db_time_from: str):
        """Retrieve orders for a user."""
        orders = user_snapshot.get("orders").get("ebay")
        if not orders:
            return {"orders": [], "error": "No orders found"}

        if db_time_from:
            db_time_from_obj = datetime.fromisoformat(db_time_from)
            orders = [
                order
                for order in orders
                if datetime.fromisoformat(order["dateOrdered"]) >= db_time_from_obj
            ]

        return {"orders": orders[offset - 1 : offset - 1 + limit], "error": None}
    

    @handle_firestore_errors
    def add_orders(self, user_ref: DocumentReference, user_snapshot: DocumentSnapshot, orders: list):
        # Access the "orders" field in the user document
        orders_field = user_snapshot.get("orders").get("ebay")

        # If "orders" does not exist, create it as an empty dictionary
        if not orders_field:
            orders_field = {}

        try:
            # Iterate through the orders (assuming the structure provided)
            for order in orders:
                if order["orderId"]:
                    # Ensure the "image" field is always a list
                    if order.get('image') is None:
                        order['image'] = []  # Set to an empty list if no image exists
                    elif isinstance(order['image'], str):
                        order['image'] = [order['image']]  # Wrap in a list if it's a string

                    # Add the order data to the user's "orders" field under the specific order_id
                    orders_field[order["orderId"]] = order

            # Update the user's document with the modified orders
            user_ref.update({
                "orders.ebay": orders_field
            })

            return {"success": True, "message": "Orders added successfully"}
        
        except Exception as error:
            print(error)
            return {"success": False, "message": str(error)}


    @handle_firestore_errors
    def remove_order(self, user_ref, order_id):
        """Remove an order from the user's orders."""
        orders_field = user_ref.get("orders")
        
        # Check if the order exists in the "orders" field
        if orders_field and order_id in orders_field:
            # Remove the order by deleting the key (order_id) from the dictionary
            del orders_field[order_id]
            
            # Update the user's document with the modified orders field
            user_ref.update({
                "orders": orders_field
            })

            return {"success": True, "message": "Order removed successfully"}
        else:
            return {"success": False, "message": "Order not found"}