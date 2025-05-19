# External Imports
from bs4 import BeautifulSoup
from urllib.parse import urlparse

import tls_client
import traceback
import ssl

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
    "Accept": "*/*",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
}


def http_request(url: str):
    try:
        headers = {**HEADERS, "Referer": get_root(url)}

        session = tls_client.Session(
            client_identifier="chrome112", random_tls_extension_order=True
        )

        response = session.get(url, headers=headers)

        if response.status_code != 200:
            raise Exception(
                f"Response returned {response.status_code} | {response.content}"
            )

        return BeautifulSoup(response.text, "lxml")

    except Exception:
        print(traceback.format_exc())


def make_ssl_context():
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def get_root(url: str) -> str:
    parts = urlparse(url)
    return f"{parts.scheme}://{parts.netloc}"
