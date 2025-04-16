# Local Imports
from ..utils import format_date_to_iso
from ..models import OrderStatus

# External Imports
from datetime import datetime, timezone, timedelta

import traceback


def extract_refund_data(
    order: dict,
    is_cancelled: bool,
):
    try:
        if not is_cancelled:
            return None

        refund_info = order.get("MonetaryDetails", {}).get("Refunds", {}).get("Refund")
        if refund_info is None:
            return None

        return {
            "status": refund_info.get("RefundStatus"),
            "type": refund_info.get("RefundType"),
            "amount": abs(
                float(refund_info.get("RefundAmount", {}).get("value", "0.0"))
            ),
            "currency": refund_info.get("RefundAmount", {}).get("_currencyID", "GBP"),
            "refundedTo": refund_info.get("RefundTo", {}).get("value"),
            "refundedAt": refund_info.get("RefundTime"),
            "referenceId": refund_info.get("ReferenceID", {}).get("value"),
        }

    except Exception as error:
        print(f"Error in get_refund_data: ", error)
        print(traceback.format_exc())
        return {}


def extract_history_data(
    order_status: str,
    transaction: dict,
    shipping: dict,
    refund: dict,
    sale_price: int,
    modification_date: str,
    db_history: list = None,  # List of existing history dictionaries
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

    try:
        # For these statuses, we want to add the earlier events first.
        # Always add the "Order Placed" event if it does not exist.
        if order_status in [
            "Active",
            "InProcess",
            "Completed",
            "CancelPending",
            "Cancelled",
        ]:
            status = (
                order_status if order_status in ["InProcess", "Active"] else "Active"
            )
            # Using transaction["CreatedDate"] as the order placement time.
            add_event(
                "Sold",
                f"Order placed on eBay {transaction['Item'].get('Site', 'eBay')} for {sale_price}",
                status,
                transaction["CreatedDate"],
            )

        # If we have shipping data and a shipped time, add the "Shipped" event.
        if shipping and shipping.get("shippedAt"):
            status = (
                order_status if order_status in ["InProcess", "Active"] else "InProcess"
            )
            tracking = shipping.get("trackingNumber", "N/A")
            add_event(
                "Shipped",
                f"Shipped to eBay buyer. Tracking {'#' if tracking != 'N/A' else ''}{tracking}",
                status,
                shipping["shippedAt"],
            )

        # Next, depending on the order status, add the later event(s)
        if order_status == "Completed":
            # For completed orders, add the "Completed" event after the other events.
            add_event("Completed", "Order Completed", order_status, modification_date)

        elif order_status == "CancelPending":
            # Cancellation may have a refund indicator.
            if refund:
                if refund.get("refundedTo") == "eBayPartner":
                    add_event(
                        "Cancellation Requested",
                        "You requested to cancel this order",
                        order_status,
                        refund.get("refundedAt", modification_date),
                    )
                elif refund.get("refundedTo") == "eBayUser":
                    add_event(
                        "Cancellation Requested",
                        "Buyer requested cancellation",
                        order_status,
                        refund.get("refundedAt", modification_date),
                    )
                else:
                    add_event(
                        "Cancellation Requested",
                        "Cancellation pending",
                        order_status,
                        refund.get("refundedAt", modification_date),
                    )
            else:
                add_event(
                    "Cancellation Requested",
                    "Cancellation pending",
                    order_status,
                    modification_date,
                )

        elif order_status == "Cancelled":
            # For cancelled orders, if there is refund data, record "Refunded",
            # otherwise simply "Cancelled".
            if refund:
                add_event(
                    "Refunded",
                    "Order was cancelled and refunded",
                    order_status,
                    refund.get("refundedAt", modification_date),
                )
            else:
                add_event(
                    "Cancelled", "Order was cancelled", order_status, modification_date
                )

        # For "InProcess" orders (if not already covered in shipping) you might want a fallback:
        elif order_status == "InProcess":
            # InProcess indicates the order is being processed (often meaning it's been shipped)
            if not (shipping and shipping.get("shippedTime")):
                add_event(
                    "Shipped",
                    f"Order is in process and will be shipped soon.",
                    order_status,
                    modification_date,
                )

    except Exception as error:
        print("Error in extract_history_data:", error)
        print(traceback.format_exc())

    new_events.sort(key=lambda e: e["timestamp"])
    return new_events


def extract_shipping_details(order: dict, shipping_details: dict):
    try:
        # Parse dates safely
        shipped_time = (
            datetime.fromisoformat(
                order.get("ShippedTime", "").replace("Z", "+00:00").replace(" ", "")
            )
            if order.get("ShippedTime")
            else None
        )
        paid_time = (
            datetime.fromisoformat(
                order.get("PaidTime", "").replace("Z", "+00:00").replace(" ", "")
            )
            if order.get("PaidTime")
            else None
        )
        actual_delivery_time = (
            datetime.fromisoformat(
                order.get("ShippingServiceSelected", {})
                .get("ShippingPackageInfo", {})
                .get("ActualDeliveryTime", "")
                .replace("Z", "+00:00")
                .replace(" ", "")
            )
            if order.get("ShippingServiceSelected", {})
            .get("ShippingPackageInfo", {})
            .get("ActualDeliveryTime")
            else None
        )

        tracking_details = (
            shipping_details.get("ShipmentTrackingDetails", {})
            if shipping_details.get("ShipmentTrackingDetails")
            else {}
        )

        return {
            "fees": extract_shipping_cost(order),
            "shippedAt": format_date_to_iso(shipped_time) if shipped_time else None,
            "paymentToShipped": (
                (shipped_time - paid_time).days if shipped_time and paid_time else None
            ),
            "service": tracking_details.get("ShippingCarrierUsed", ""),
            "timeDays": (
                (actual_delivery_time - shipped_time).days
                if actual_delivery_time and shipped_time
                else None
            ),
            "trackingNumber": tracking_details.get("ShipmentTrackingNumber"),
        }

    except Exception as error:
        print(f"Error in get_shipping_details: ", error)
        print(traceback.format_exc())
        print(order)
        return {}


def extract_shipping_cost(order):
    shipping_service_options = order["ShippingDetails"].get(
        "ShippingServiceOptions", []
    )

    if len(shipping_service_options) == 0:
        return 0

    shipping_fees = 0

    try:
        # Handle if the shipping fees are stored in a list
        # This can occur if eBay has to authenticate an item
        if isinstance(shipping_service_options, list):
            if shipping_service_options[0].get("ShippingServiceCost") is not None:
                shipping_fees = float(
                    shipping_service_options[0]["ShippingServiceCost"]["value"]
                )
        # Handle if the shipping fees are stored in a dict
        else:
            if shipping_service_options.get("ShippingServiceCost") is not None:
                shipping_fees = float(
                    shipping_service_options["ShippingServiceCost"]["value"]
                )

    except Exception as error:
        print("Error in calculate_shipping_cost: ", error)

    finally:
        return shipping_fees


def extract_time_key(time_from: str) -> str:
    """
    Determine whether to use 'CreateTimeFrom' or 'ModTimeFrom' based on the provided 'time_from'.
    """
    time_from_dt = datetime.fromisoformat(time_from.replace("Z", "")).replace(
        tzinfo=timezone.utc
    )
    if datetime.now(timezone.utc) - time_from_dt < timedelta(days=30):
        return "ModTimeFrom"
    return "CreateTimeFrom"
