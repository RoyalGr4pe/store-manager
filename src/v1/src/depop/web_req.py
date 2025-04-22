# Local Imports
from ..constants import COOKIEJAR_PATH

# External Imports
from urllib.parse import urlparse
from fake_headers import Headers

import tls_client
import pickle
import json
import os


def headers(gen=False):
    """
    Generate random headers
    """
    if gen is True:
        return Headers(headers=True).generate()
    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/png,image/svg+xml,*/*;q=0.8",
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "Accept-Language": "en-GB,en;q=0.5",
        "Host": "duckduckgo.com",
        "TE": "trailers",
        "Cookie": "ae=d; ay=b; 5=2; t=b; a=a; 9=8ab4f8; ai=-1; aa=c58af9; 7=202124; x=8ab4f8",
        "DNT": "1",
        "PRIORITY": "u=0, i",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Sec-GPC": "1",
        "Upgrade-Insecure-Requests": "1",
        "Referer": "https://www.depop.com/",
    }


def load_cookies():
    """
    Load cookies from the local cookiejar file.
    """
    if os.path.exists(COOKIEJAR_PATH) and os.path.getsize(COOKIEJAR_PATH) > 0:
        try:
            with open(COOKIEJAR_PATH, "rb") as f:
                return pickle.load(f)
        except EOFError:
            return {}
    return {}


def save_cookies(cookies):
    """
    Save cookies to the local cookiejar file.
    """
    with open(COOKIEJAR_PATH, "wb") as f:
        pickle.dump(cookies, f)


def get_domain(url):
    """
    Extract domain from URL
    """
    parsed_url = urlparse(url)
    return parsed_url.netloc


async def check_response_status(status_code, url):
    if status_code in [302, 303, 500, 502, 503]:
        # These status codes are due to the server not the request
        print(
            f"({url}), Response Status Code {str(status_code)}: This status code us due to the server not the request"
        )
        return None

    elif status_code in [301, 308, 400, 404, 410]:
        # These status codes indicate the resource has been moved or there was a bad request
        print(
            f"({url}), Response Status Code {str(status_code)}. This status code indicates the resource has been moved or there was a bad request"
        )
        return None

    elif status_code in [403]:
        # 403 is a forbidden error
        print(f"({url}), Response Status Code {str(status_code)}")
        return None

    elif status_code != 200:
        # Any other error should be logged so it can be handled in the future
        print(f"({url}), Response Status Code {str(status_code)}")
        return None

    else:
        return True


async def tls_client_request(url):
    response = None
    try:
        cookies = load_cookies()

        with tls_client.Session(
            client_identifier="chrome112", random_tls_extension_order=True
        ) as session:
            domain = get_domain(url)

            # Update cookies for the domain in tls_client session
            session.cookies.update(cookies.get(domain, {}))

            # Make request using tls_client
            response = await tls_client_fetch(url, session)

            # Update cookies after request
            cookies[domain] = session.cookies

        # Save updated cookies to file
        save_cookies(cookies)

        return json.loads(response)

    except Exception as error:
        print("Failed tls_client_request: %s", error)


async def tls_client_fetch(url, session):
    try:
        response = session.get(url, headers=headers())
        status = response.status_code

        # Redirect: Send a request to the redirected url
        if status in [302, 303]:
            redirect_url = response.headers.get("Location")
            if redirect_url:
                print("Error redirect")

        if await check_response_status(status, url):
            return response.content
        return {"status": status}

    except Exception as error:
        print("Failed request for (%s): %s", url, error)
