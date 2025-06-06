from dotenv import load_dotenv

import os

load_dotenv()

# Max items fetched before the current month
history_limits = {"Free - member": 50, "Standard - member": 100, "Pro - member": 500, "Enterprise 1 - member": 700, "Enterprise 2 - member": 800, "Enterprise 3 - member": 900, "Enterprise 4 - member": 1000}


# Path to the cookiejar file
COOKIEJAR_PATH = "cookies.pkl"


# eBay Limits
max_ebay_order_limit_per_page = 200
max_ebay_listing_limit_per_page = 200

# Depop Limits
max_depop_order_limit_per_page = 200
max_depop_listing_limit_per_page = 200

# DB Keys & Collections
inventory_key = "inventory"
sale_key = "orders"

inventory_id_key = "itemId"
sale_id_key = "transactionId"

MAX_WHILE_LOOP_DEPTH = int(os.getenv("MAX_WHILE_LOOP_DEPTH"))
