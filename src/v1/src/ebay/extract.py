# Local Imports
from ..utils import format_date_to_iso

# External Imports
from datetime import datetime, timezone, timedelta
from pprint import pprint

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
        
        if (isinstance(refund_info, list) and len(refund_info) > 0):
            refund_info = refund_info[0]

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
        print(traceback.format_exc())


def extract_shipping_details(order: dict, shipping_details: dict):
    try:

        tracking_details = (
            shipping_details.get("ShipmentTrackingDetails", {})
            if shipping_details.get("ShipmentTrackingDetails")
            else {}
        )

        if (isinstance(tracking_details, list) and len(tracking_details) > 0):
            tracking_details = tracking_details[0]
        elif (isinstance(tracking_details, list)):
            tracking_details = {}

        return {
            "fees": extract_shipping_cost(order),
            "date": order.get("ShippedTime") if order.get("ShippedTime") else None,
            "service": tracking_details.get("ShippingCarrierUsed", ""),
            "trackingNumber": tracking_details.get("ShipmentTrackingNumber"),
        }

    except Exception as error:
        print(traceback.format_exc())
        return {}


def extract_taxes(transaction: dict):
    taxes = transaction.get("Taxes")

    if (not taxes): return

    total_amount = taxes.get("TotalTaxAmount")
    tax_details = taxes.get("TaxDetails")

    try: 
        value = float(total_amount.get("value"))
        currency = total_amount.get("_currencyID")

        return {
            "amount": value,
            "currency": currency,
            "type": tax_details.get("Imposition"),
            "description": tax_details.get("TaxDescription")
        }

    except Exception as error:
        print(traceback.format_exc())

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
        print(traceback.format_exc())
        raise error

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


{
    "OrderID": "16-12722-37322",
    "OrderStatus": "Completed",
    "AdjustmentAmount": {"_currencyID": "GBP", "value": "0.0"},
    "AmountPaid": {"_currencyID": "GBP", "value": "35.62"},
    "AmountSaved": {"_currencyID": "GBP", "value": "0.0"},
    "CheckoutStatus": {
        "eBayPaymentStatus": "NoPaymentFailure",
        "LastModifiedTime": "2025-02-26T21:43:01.000Z",
        "PaymentMethod": "CustomCode",
        "Status": "Complete",
        "IntegratedMerchantCreditCardEnabled": "false",
    },
    "ShippingDetails": {
        "SalesTax": {"ShippingIncludedInTax": "false"},
        "ShippingServiceOptions": {
            "ShippingService": "UK_YodelStoreToDoor",
            "ShippingServiceCost": {"_currencyID": "GBP", "value": "3.71"},
            "ShippingServicePriority": "1",
            "ExpeditedService": "false",
            "ShippingTimeMin": "2",
            "ShippingTimeMax": "4",
        },
        "SellingManagerSalesRecordNumber": "148",
    },
    "CreatedTime": "2025-02-19T08:20:56.000Z",
    "ShippingAddress": {
        "Name": "Ekene  Obi",
        "Street1": "118 qlenurquhart road",
        "Street2": "Behind the main building",
        "CityName": "Inverness",
        "StateOrProvince": "Highland",
        "Country": "GB",
        "CountryName": "United Kingdom",
        "Phone": "447775371644",
        "PostalCode": "Iv3 5pb",
        "AddressID": "10003041780341",
        "AddressOwner": "eBay",
    },
    "ShippingServiceSelected": {
        "ShippingService": "UK_YodelStoreToDoor",
        "ShippingServiceCost": {"_currencyID": "GBP", "value": "3.71"},
        "ShippingPackageInfo": {"ActualDeliveryTime": "2025-02-24T14:14:01.000Z"},
    },
    "Subtotal": {"_currencyID": "GBP", "value": "29.99"},
    "Total": {"_currencyID": "GBP", "value": "35.62"},
    "TransactionArray": {
        "Transaction": [
            {
                "Buyer": {
                    "Email": "Invalid Request",
                    "UserFirstName": None,
                    "UserLastName": None,
                },
                "ShippingDetails": {
                    "SellingManagerSalesRecordNumber": "148",
                    "ShipmentTrackingDetails": {
                        "ShippingCarrierUsed": "Yodel",
                        "ShipmentTrackingNumber": "87RLK0006654A085",
                    },
                },
                "CreatedDate": "2025-02-19T08:20:56.000Z",
                "Item": {
                    "ItemID": "387482773546",
                    "Site": "UK",
                    "Title": "Adidas Originals Ozmillen Men's Trainers, Size 9, Grey/White/Heather",
                },
                "QuantityPurchased": "1",
                "Status": {"PaymentHoldStatus": "Released"},
                "TransactionID": "1599219075025",
                "TransactionPrice": {"_currencyID": "GBP", "value": "29.99"},
                "ShippedTime": "2025-02-19T12:42:56.000Z",
                "TransactionSiteID": "UK",
                "Platform": "eBay",
                "Taxes": {
                    "TotalTaxAmount": {"_currencyID": "GBP", "value": "0.32"},
                    "TaxDetails": {
                        "Imposition": "CustomCode",
                        "TaxDescription": "CustomCode",
                        "TaxAmount": {"_currencyID": "GBP", "value": "0.32"},
                        "TaxOnSubtotalAmount": {"_currencyID": "GBP", "value": "0.32"},
                        "TaxOnShippingAmount": {"_currencyID": "GBP", "value": "0.0"},
                        "TaxOnHandlingAmount": {"_currencyID": "GBP", "value": "0.0"},
                    },
                },
                "ActualShippingCost": {"_currencyID": "GBP", "value": "3.71"},
                "ActualHandlingCost": {"_currencyID": "GBP", "value": "0.0"},
                "OrderLineItemID": "387482773546-1599219075025",
                "InventoryReservationID": "1599219075025",
                "eBayPlusTransaction": "false",
            }
        ]
    },
    "BuyerUserID": "ek-8549",
    "PaidTime": "2025-02-19T08:20:55.609Z",
    "ShippedTime": "2025-02-19T12:42:56.000Z",
    "EIASToken": "nY+sHZ2PrBmdj6wVnY+sEZ2PrA2dj6MBkIOiCpiEogudj6x9nY+seQ==",
    "PaymentHoldStatus": "Released",
    "IsMultiLegShipping": "false",
    "MonetaryDetails": {
        "Payments": {
            "Payment": [
                {
                    "PaymentStatus": "Succeeded",
                    "Payer": {"_type": "eBayUser", "value": "ek-8549"},
                    "Payee": {"_type": "eBayUser", "value": "flippify"},
                    "PaymentTime": "2025-02-19T08:20:55.609Z",
                    "PaymentAmount": {"_currencyID": "GBP", "value": "33.7"},
                    "ReferenceID": {
                        "_type": "ExternalTransactionID",
                        "value": "2370617026903",
                    },
                    "FeeOrCreditAmount": {"_currencyID": "GBP", "value": "0.0"},
                },
                {
                    "PaymentStatus": "Succeeded",
                    "Payer": {"_type": "eBayUser", "value": "ek-8549"},
                    "Payee": {"_type": "eBayUser", "value": "eBay"},
                    "PaymentTime": "2025-02-19T08:20:55.609Z",
                    "PaymentAmount": {"_currencyID": "GBP", "value": "1.92"},
                    "ReferenceID": {
                        "_type": "ExternalTransactionID",
                        "value": "2370617026903",
                    },
                    "FeeOrCreditAmount": {"_currencyID": "GBP", "value": "1.92"},
                },
            ]
        }
    },
    "ContainseBayPlusTransaction": "false",
}
