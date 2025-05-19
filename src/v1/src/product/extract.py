# External Imports
from bs4 import BeautifulSoup

import tldextract


def extract_meta(html: BeautifulSoup) -> dict:
    meta = {}

    # 1. Page title
    title_tag = html.find('title')
    if title_tag and title_tag.string:
        meta['title'] = title_tag.string.strip()

    # 2. All <meta> tags
    for tag in html.find_all('meta'):
        # Determine key: prefer property over name
        key = tag.get('property') or tag.get('name')
        if not key:
            continue
        content = tag.get('content')
        if not content:
            continue
        meta[key.strip()] = content.strip()

    return meta


def parse_product_data(meta: dict) -> dict:
    # Title: prefer Open Graph, fallback to title tag
    title = meta.get('og:title') or meta.get('title')

    # Description: prefer Open Graph, fallback to meta description
    description = meta.get('og:description') or meta.get('description')

    # URL
    url = meta.get('og:url')

    # Price
    price = None
    price_amount = meta.get('product:price:amount') or meta.get('og:price:amount')
    price_currency = meta.get('product:price:currency') or meta.get('og:price:currency')
    if price_amount:
        try:
            price = {
                'amount': float(price_amount),
                'currency': price_currency
            }
        except ValueError:
            price = {'amount': price_amount, 'currency': price_currency}
    else:
        for i in range(1, 6):
            label = meta.get(f'twitter:label{i}', '').lower()
            data = meta.get(f'twitter:data{i}', '')
            if 'price' in label and data:
                # parse currency and amount
                amt = data.replace('£', '').replace('$', '').replace('€', '').strip()
                try:
                    amt_val = float(amt)
                except ValueError:
                    amt_val = data
                # infer currency symbol
                currency = 'GBP' if '£' in data else ('USD' if '$' in data else None)
                price = {'amount': amt_val, 'currency': currency}
                break

    # Images: collect og:image and twitter:image
    image = []
    if 'og:image' in meta:
        image.append(meta['og:image'])
    if 'twitter:image' in meta and meta['twitter:image'] not in image:
        image.append(meta['twitter:image'])
    # Fallback to any image tags in meta dict
    for key, val in meta.items():
        if key.startswith('og:image:') and val not in image:
            image.append(val)

    image = list(set(image))
    

    return {
        "title": title,
        "description": description,
        "url": url,
        "image": image,
        "price": price,
        "marketplace": extract_domain_name(url)
    }


def extract_domain_name(url: str) -> str:
    ext = tldextract.extract(url)
    return ext.domain