def sold_url(shop_id: str, limit: int = 24, offset_id: str = None):
    url = f"https://webapi.depop.com/api/v2/shop/{shop_id}/filteredProducts/sold/?lang=en&limit={limit}&force_fee_calculation=false"

    if offset_id:
        url += f"&offset_id={offset_id}"

    return url

def inventory_url(shop_id: str, limit: int = 24, offset_id: str = None):
    url = f"https://webapi.depop.com/api/v3/shop/{shop_id}/products/?limit={limit}&force_fee_calculation=false"

    if offset_id:
        url += f"&after={offset_id}"

    return url
