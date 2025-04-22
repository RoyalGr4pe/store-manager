from ..models import OrderStatus

def extract_quantity(listing: dict):
    # Step 1: Extract quantity data
    variants: dict = listing.get("variants")

    # Step 2: If there is no variants key-pair then its a singular item
    if variants is None:
        return 1

    # Step 3: Sum up the variants values
    return sum([val for val in variants.values()])


def extract_price(pricing: dict):
    # Step 1: Extract original price
    original_price = float(pricing.get("original_price", {}).get("total_price"))

    # Step 2: Extract discounted price
    discounted_price = None
    discounted_price_dict: dict = pricing.get("discounted_price")
    if discounted_price_dict is not None:
        discounted_price = float(discounted_price_dict.get("total_price"))
        
    return original_price, discounted_price


def extract_shipping(shipping: dict):
    return {
        "fees": float(shipping.get("total_price", 0)),
        "paymentToShipped": None,
        "service": shipping.get("type"),
        "shippedAt": None,
        "timeDays": None,
        "trackingNumber": None,
    }


def extract_history(
    status: OrderStatus,
    modification_date: str,
    db_history: list = None,
):
    # We'll accumulate new events in this list.
    new_events = []

    # Helper: check if an event with the given title (and optionally close timestamp) already exists.
    def already_exists(title: str) -> bool:
        if db_history:
            for event in db_history:
                if event.get("title") == title:
                    return True
        return False

    # Helper: add event if not already present
    def add_event(title: str, description: str, status: OrderStatus, timestamp: str):
        if not already_exists(title):
            new_events.append(
                {
                    "title": title,
                    "description": description,
                    "status": status,
                    "timestamp": timestamp,
                }
            )

    if status == "Completed":
        # For completed orders, add the "Completed" event after the other events.
        add_event("Completed", "Order Completed", status, modification_date)

def extract_image(item: dict):
    image = list(item.get("preview", {}).values())
    if len(image) > 0:
        image = [image[-1]]
    else:
        image = []

    return image
