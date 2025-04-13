from dotenv import load_dotenv
from google.oauth2 import service_account
from google.cloud import firestore 

import threading
import traceback
import os

load_dotenv()

# Global variable to hold Firestore client and status
db = None
status_config = {
    "status": "unknown",
    "api": {
        "ebay": "unknown"
    }
}

# Now you can build your API status dictionary using the current_status variable
title = "Flippify Store API"
description = "API for fetching and updating eBay listings and orders"
version = "1.0.1"

config = {
    "name": title,
    "description": description,
    "version": version,
    "status": status_config,
    "docs": "https://api.flippify.io/docs",
}

callback_done = threading.Event()


def get_db():
    global db
    if db:
        return db

    FIREBASE_PROJECT_ID = os.getenv("FIREBASE_PROJECT_ID")
    FIREBASE_PRIVATE_KEY_ID = os.getenv("FIREBASE_PRIVATE_KEY_ID")
    FIREBASE_PRIVATE_KEY = os.getenv("FIREBASE_PRIVATE_KEY").replace("\\n", "\n")
    FIREBASE_CLIENT_EMAIL = os.getenv("FIREBASE_CLIENT_EMAIL")
    FIREBASE_CLIENT_ID = os.getenv("FIREBASE_CLIENT_ID")
    FIREBASE_CLIENT_X509_CERT_URL = os.getenv("FIREBASE_CLIENT_X509_CERT_URL")

    try:
        credentials = service_account.Credentials.from_service_account_info(
            {
                "type": "service_account",
                "project_id": FIREBASE_PROJECT_ID,
                "private_key_id": FIREBASE_PRIVATE_KEY_ID,
                "private_key": FIREBASE_PRIVATE_KEY,
                "client_email": FIREBASE_CLIENT_EMAIL,
                "client_id": FIREBASE_CLIENT_ID,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
                "client_x509_cert_url": FIREBASE_CLIENT_X509_CERT_URL,
                "universe_domain": "googleapis.com",
            }
        )

        db = firestore.Client(project=FIREBASE_PROJECT_ID, credentials=credentials)
        return db

    except Exception as error:
        print("Error initializing Firestore:", error)
        print(traceback.format_exc())


def on_status_snapshot(doc_snapshot, changes, read_time):
    global status_config
    try:
        for doc in doc_snapshot:
            status_config = doc.to_dict()
            config["status"] = status_config
            print(f"Received document snapshot: {doc.id} with status: {status_config}")
        callback_done.set()  # Signal that at least one snapshot has been received
    except Exception as error:
        print("Error in on_status_snapshot:", error)
        print(traceback.format_exc())


def start_status_listener():
    db_client = get_db()
    status_ref = db_client.collection("config").document("status")
    # Watch the document for real-time updates.
    doc_watch = status_ref.on_snapshot(on_status_snapshot)
    # Optionally, you can return doc_watch so you can unsubscribe later:
    return doc_watch


# Start the listener (this will run in the background)
doc_watch = start_status_listener()

# Wait for the initial snapshot before continuing (if needed)
callback_done.wait(timeout=10)  # waits up to 10 seconds
