"""Polite HTTP helpers shared by all sources.

"Polite" means: we say who we are (User-Agent), we never wait forever
(timeout), and we pause a little between requests so we don't hammer
anybody's server.
"""

from __future__ import annotations

import time
from typing import Any

import requests

USER_AGENT = (
    "opportunity-radar/1.0 (personal student job-alert bot; "
    "+https://github.com/PedroCamargoLINCE/opportunity-radar)"
)
TIMEOUT_SECONDS = 25
DELAY_SECONDS = 0.6  # pause before every request

_session = requests.Session()
_session.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.8,pt-BR;q=0.6"})


RATE_LIMIT_WAITS = (15, 45)  # seconds to wait after a "429 Too Many Requests"


def _request(method: str, url: str, **kwargs: Any) -> requests.Response:
    """Send one request.

    Network errors and 5xx answers get one more try. A 429 ("too many
    requests, slow down") gets up to two more tries after longer pauses, as
    the site asked. Other 4xx answers fail straight away.
    """
    kwargs.setdefault("timeout", TIMEOUT_SECONDS)
    waits = [DELAY_SECONDS, DELAY_SECONDS * 2]  # pause before each try
    slow_down_waits = list(RATE_LIMIT_WAITS)
    last_error: Exception | None = None
    while waits:
        time.sleep(waits.pop(0))
        try:
            response = _session.request(method, url, **kwargs)
        except requests.RequestException as error:
            last_error = error
            continue
        if response.status_code == 429 and slow_down_waits:
            waits.insert(0, slow_down_waits.pop(0))  # wait longer, then try again
            last_error = requests.HTTPError(f"429 Too Many Requests from {url}")
            continue
        if response.status_code >= 500:
            last_error = requests.HTTPError(f"{response.status_code} from {url}")
            continue
        response.raise_for_status()  # other 4xx: no point retrying
        return response
    assert last_error is not None
    raise last_error


def get_json(url: str, **kwargs: Any) -> Any:
    """GET a URL and parse the answer as JSON."""
    return _request("GET", url, **kwargs).json()


def post_json(url: str, payload: dict[str, Any], **kwargs: Any) -> Any:
    """POST a JSON body and parse the JSON answer."""
    return _request("POST", url, json=payload, **kwargs).json()


def get_text(url: str, **kwargs: Any) -> str:
    """GET a URL and return the body as text (HTML, Markdown...)."""
    response = _request("GET", url, **kwargs)
    response.encoding = response.encoding or "utf-8"
    return response.text
