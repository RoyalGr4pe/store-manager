# Local Imports
from ..utils import format_date_to_iso

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
):
    # History
    history_title = None
    history_description = None
    history_timestamp = None

    try:
        if order_status == "Active":
            """
            Definition:
            - Indicates that the order is not yet complete. In this state, the buyer has not initiated payment.

            Usage & Implications:
            - This order status is used while the buyer has the option to combine the order into a Combined Invoice or request a cancellation.
            - The seller can also update payment or shipping details while the order remains active.
            """
            history_title = "Order Placed"
            country_code = transaction["Item"].get("Site", "eBay")
            history_description = (
                f"Order placed on eBay {country_code} for {sale_price}"
            )
            history_timestamp = transaction["CreatedDate"]

        elif order_status == "InProcess":
            """
            Definition:
            - Indicates that the order is currently being processed but is not yet complete.

            Usage & Implications:
            - Although the order is being worked on, it has not reached finalization, meaning that adjustments, fulfillment steps, or cancellations might still occur.
            - This status is returned in order management responses, even though it is not supported as a filter value in GetOrders requests.

            Context:
            - It reflects a transitional state where the order is progressing toward completion but remains open to changes.
            """
            history_title = "Shipped"
            history_description = (
                f"Shipped to eBay buyer. Tracking {shipping['trackingNumber']}"
            )
            history_timestamp = shipping.get("shippedTime", modification_date)

        elif order_status == "Completed":
            """
            Definition:
            - Denotes that the order has been fully processed and completed, including being paid for.

            Usage & Implications:
            - No further changes can be made to an order once it is marked as Completed.
            - It is used both as a filter in GetOrders requests and as a response value in various order management API calls.

            Key Point:
            - The Completed status is the final state for a transaction that has successfully gone through the full sales process.
            """
            history_title = "Completed"
            history_description = "Order Completed"
            history_timestamp = modification_date

        elif order_status == "CancelPending":
            """
            Definition:
            - Indicates that the buyer has initiated a cancellation request for the order.

            Usage & Implications:
            - When an order is in this status, the seller must take action either to approve or reject the cancellation through My eBay or via API cancellation calls.
            - Note that this value cannot be used as an OrderStatus filter value in the GetOrders request payload.

            Important:
            - It acts as an intermediary state while the cancellation is being processed.
            """
            history_title = "Cancellation Requested"
            if refund:
                if refund.get("refundedTo") == "eBayPartner":
                    history_description = "You requested to cancel this order"
                elif refund.get("refundedTo") == "eBayUser":
                    history_description = "Buyer requested cancellation"
                else:
                    history_description = "Cancellation pending"
                history_timestamp = refund.get("refundedAt", modification_date)
            else:
                history_description = "Cancellation pending"
                history_timestamp = modification_date

        elif order_status == "Cancelled":
            """
            Definition:
            - Signifies that the order has been cancelled.

            Usage & Implications:
            - After cancellation, if payment was made, the seller might be required to refund the buyer.
            - This status is available as a filter in the GetOrders request and is returned in order management responses.
            """
            history_title = "Cancelled"
            history_description = "Order was cancelled and refunded"
            if refund:
                history_title = "Refunded"
                history_timestamp = refund.get("refundedAt", modification_date)
            else:
                history_timestamp = modification_date

    except Exception as error:
        print("error in get_history_data", error)
        print(traceback.format_exc())

    return {
        "title": history_title,
        "description": history_description,
        "timestamp": history_timestamp,
    }


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
