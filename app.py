# Local Imports
from src.process_listings import fetch_listings, set_listing_query_params
from src.process_orders import fetch_orders, set_order_query_params
from src.handler_limits import fetch_users_limits, filter_return_records
from src.handler_ebay import refresh_ebay_access_token, refresh_ebay_token_direct
from src.db_firebase import FirebaseDB

# External Imports
from flask import Flask, jsonify, request
from flask_cors import CORS
from flask_jwt_extended import (
    JWTManager,
    jwt_required,
    create_access_token,
    get_jwt_identity,
    create_refresh_token,
)
from dotenv import load_dotenv
from datetime import timedelta, timezone, datetime

import os


# Load environment variables from .env
load_dotenv()


# Initialize Flask application
app = Flask(__name__)
CORS(app)
# Setup JWT authentication secret key
# Access token expires in 1 hour
# Refresh token expires in 30 days
app.config["JWT_SECRET_KEY"] = os.getenv("JWT_SECRET_KEY")
app.config["JWT_ACCESS_TOKEN_EXPIRES"] = timedelta(hours=1)
app.config["JWT_REFRESH_TOKEN_EXPIRES"] = timedelta(days=30)

# Initialize JWT manager
jwt = JWTManager(app)


# Connect to Mongo and Firebase
# Database Initialization
firebase_db = None

def get_firebase_db():
    global firebase_db
    if not firebase_db:
        firebase_db = FirebaseDB()
    return firebase_db


# Authentication endpoint for generating JWT
@app.route("/login", methods=["POST"])
def login():
    firebase_db = get_firebase_db()
    
    oauth_token = request.json.get("token")
    uid = request.json.get("uid")

    if not oauth_token or not uid:
        return jsonify({"msg": "Missing token or uid"}), 400

    user_ref = firebase_db.query_user_ref(uid)
    user_snapshot = user_ref.get()

    if user_snapshot.exists is False:
        return jsonify({"msg": "User could not be found"}), 400

    # Check if eBay token needs refreshing
    connected_accounts = user_snapshot.get("connectedAccounts")
    ebay_data = connected_accounts.get("ebay")
    if ebay_data is None:
        return jsonify({"msg": "eBay account not connected"}), 400
    ebay_access_token = ebay_data.get("ebayAccessToken")
    ebay_token_expiry = ebay_data.get("ebayTokenExpiry")  # Stored as a Unix timestamp
    
    # Convert ebay_token_expiry to seconds if it's in milliseconds
    if ebay_token_expiry > 1000000000000:  
        ebay_token_expiry /= 1000  # Convert to seconds

    current_timestamp = int(datetime.now(timezone.utc).timestamp() * 1000)  # Current time in seconds

    if ebay_token_expiry and ebay_token_expiry < current_timestamp:
        # Token is expired, refresh it
        refreshed_token_data = refresh_ebay_token_direct(firebase_db, user_ref, user_snapshot)
        if refreshed_token_data[1] != 200:
            return jsonify({"msg": refreshed_token_data[0]["error"]}), 400
        
        ebay_access_token = refreshed_token_data[0]["access_token"]

    # Query the user's subscriptions which have "member" in their name
    user_subscriptions_list = user_snapshot.get("subscriptions")
    if not user_subscriptions_list:
        return jsonify({"msg": "User does not have any subscriptions"}), 400
    user_has_member_subscription = False
    user_subscription = None

    for sub in user_subscriptions_list:
        if "member" in sub["name"]:
            user_has_member_subscription = True
            user_subscription = sub
            break
    
    if not user_has_member_subscription:
        return jsonify({"msg": "User does not have a member subscription"}), 400

    # Create the access token and refresh token
    access_token = create_access_token(
        identity={
            "token": ebay_access_token,
            "uid": uid,
            "sub_name": user_subscription["name"],
        }
    )
    refresh_token = create_refresh_token(
        identity={
            "token": ebay_access_token,
            "uid": uid,
            "sub_name": user_subscription["name"],
        }
    )

    return jsonify(access_token=access_token, refresh_token=refresh_token), 200


# Refresh token endpoint
@app.route("/refresh", methods=["POST"])
@jwt_required(refresh=True)  # Require a valid refresh token
def refresh():
    # Get the identity of the refresh token
    current_user = get_jwt_identity()
    
    # Get the new oauth_token from the request body
    oauth_token = request.json.get("oauth_token")

    # If oauth_token is provided, update the identity in the token
    if oauth_token:
        # Update the oauth_token in the current identity
        current_user["token"] = oauth_token  # Assuming "token" is the key for oauth_token in the identity
    
    # Create a new access token using the refresh token
    access_token = create_access_token(identity=current_user)

    return jsonify(access_token=access_token), 200


# Refresh eBay tokens
@app.route("/refresh-ebay-token", methods=["POST"])
@jwt_required()  # Requires a valid JWT access token
def refresh_ebay_token(uid: str):
    firebase_db = get_firebase_db()
    
    # Get the identity of the current user from JWT
    current_user = get_jwt_identity()
    uid = current_user.get("uid")

    # Fetch the user data from MongoDB
    user_ref = firebase_db.query_user_ref(uid)
    user_snapshot = user_ref.get()
    if user_snapshot.exists is False:
        return jsonify({"msg": "User not found"}), 404

    # Get the refresh token from user's data
    ebayAccountData = user_ref.get("connectedAccounts").get("ebay")
    if (ebayAccountData is None):
        return jsonify({"msg": "eBay account not connected"}), 400
    refresh_token = ebayAccountData.get("ebayRefreshToken")
    if not refresh_token:
        return jsonify({"msg": "Refresh token not found"}), 400

    try:
        # Refresh the eBay access token
        token_data = refresh_ebay_access_token(refresh_token, os.getenv("CLIENT_ID"), os.getenv("CLIENT_SECRET"))

        # Update the user's access token in the database
        firebase_db.update_user_token(uid, token_data)

        return jsonify({"access_token": token_data.get("access_token")}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    

# Active listings endpoint with additional parameters
@app.route("/active-listings", methods=["GET"])
@jwt_required()  # Protect this endpoint with JWT authentication
def active_listings():
    current_user = get_jwt_identity()
    oauth_token = current_user.get("token")
    uid = current_user.get("uid")
    sub_name = current_user.get("sub_name")

    # If one of the users values is not found return an error
    if not(oauth_token and uid and sub_name):
        return jsonify({"content": [], "error": "Could not verify user", "error-type": "UserNotFound"}), 400

    # Fetch the maximum number of records the user is allowed
    # i.e. { automatic: 30, manual: 30 }
    user_limits = fetch_users_limits(sub_name, "listings")
    firebase_db = get_firebase_db()
    user_ref = firebase_db.query_user_ref(uid)
    user_snapshot = user_ref.get()
    params = set_listing_query_params(request, user_snapshot, user_limits)
    try:
        current_no_listings_dict = user_snapshot.get("numListings")
        current_no_listings_total = current_no_listings_dict["automatic"] + current_no_listings_dict["manual"]
        current_listings = firebase_db.get_listings(user_snapshot, params["limit"], params["offset"], params["db_time_from"])

        # If the user has already hit their limit in the database then return their database listings
        if current_no_listings_total >= params["limit"]:
            return jsonify({"content": current_listings}), 200
        
        # Check if the user has hit their automatic limit
        if current_no_listings_dict["automatic"] >= params["max_listings_automatic"]:
            return jsonify({"content": [], "error": "You have hit you limit for automatically fetching listings", "error-type": "HitAutomaticLimit"}), 400
        
        # If the user has not hit their limit then we need to send a request to eBay to get more of the users data
        ebay_listings_dict = fetch_listings(oauth_token, params["max_listings_automatic"], params["offset"], params["ebay_time_from"])

        if ebay_listings_dict.get("error") is not None:
            return jsonify({"content": [], "error": str(ebay_listings_dict.get("error")), "error-type": str(type(ebay_listings_dict.get("error")))}), 400
        
        ebay_listings = ebay_listings_dict.get("content")
        if (len(ebay_listings) == 0):
            return jsonify({"content": []}), 200

        listings_list = filter_return_records(ebay_listings, current_listings, "itemId")

        firebase_db.add_listings(user_ref, user_snapshot, ebay_listings)
        firebase_db.set_last_fetched_date(user_ref, "listings", datetime.now(timezone.utc).isoformat())
        firebase_db.set_current_no_listings(user_ref, len(listings_list), current_no_listings_dict["manual"])

        return jsonify({"content": listings_list}), 200

    except Exception as error:
        return jsonify({"content": [], "error": str(error), "error-type": str(type(error)), "error-type": str(type(error))}), 500


# Orders endpoint with additional parameters
@app.route("/orders", methods=["GET"])
@jwt_required()  # Protect this endpoint with JWT authentication
def orders():
    current_user = get_jwt_identity()
    oauth_token = current_user.get("token")
    uid = current_user.get("uid")
    sub_name = current_user.get("sub_name") 

    # If one of the users values is not found return an error
    if not(oauth_token and uid and sub_name):
        return jsonify({"content": [], "error": "Could not verify user", "error-type": "UserNotFound"}), 400
    
    # Fetch the maximum number of records the user is allowed
    # i.e. { automatic: 30, manual: 30 }
    user_limits = fetch_users_limits(sub_name, "orders")
    firebase_db = get_firebase_db()
    user_ref = firebase_db.query_user_ref(uid)
    user_snapshot = user_ref.get()
    params = set_order_query_params(request, user_snapshot, user_limits)

    try:
        current_no_orders_dict = user_snapshot.get("numOrders")
        current_no_orders_total = current_no_orders_dict["automatic"] + current_no_orders_dict["manual"]
        current_orders = firebase_db.get_orders(user_snapshot, params["limit"], params["offset"], params["db_time_from"])

        # If the user has already hit their limit in the database then return their database orders
        if current_no_orders_total >= params["limit"]:
            return jsonify({"content": current_orders}), 200
        
        # Check if the user has hit their automatic limit
        if current_no_orders_dict["automatic"] >= params["max_orders_automatic"]:
            return jsonify({"content": [], "error": "You have hit you limit for automatically fetching orders", "error-type": "HitAutomaticLimit"}), 400
        
        # If the user has not hit their limit then we need to send a request to eBay to get more of the users data
        ebay_orders_dict = fetch_orders(firebase_db, user_snapshot, oauth_token, params["max_orders_automatic"], params["offset"], params["ebay_time_from"])
        #print("ebay_orders_dict: ", ebay_orders_dict)

        if ebay_orders_dict.get("error") is not None:
            return jsonify({"content": [], "error": str(ebay_orders_dict.get("error")), "error-type": str(type(ebay_orders_dict.get("error")))}), 400
        
        ebay_orders = ebay_orders_dict.get("content")
        if (len(ebay_orders) == 0):
            return jsonify({"content": []}), 200

        orders_list = filter_return_records(ebay_orders, current_orders, "orderId")

        firebase_db.add_orders(user_ref, user_snapshot, ebay_orders)
        firebase_db.set_last_fetched_date(user_ref, "orders", datetime.now(timezone.utc).isoformat())
        firebase_db.set_current_no_orders(user_ref, len(orders_list), current_no_orders_dict["manual"])

        return jsonify({"content": orders_list}), 200

    except Exception as error:
        return jsonify({"content": [], "error": str(error), "error-type": str(type(error))}), 500



if __name__ == "__main__":
    app.run(debug=True)