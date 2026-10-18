import json
from typing import Any
from urllib import error, parse, request


def get_json(url: str, timeout: int = 45) -> dict[str, Any]:
    req = request.Request(url, headers={"Accept": "application/json"})
    try:
        with request.urlopen(req, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Provider API error {exc.code}: {body}") from exc
    except Exception as exc:
        raise RuntimeError(f"Provider API request failed: {exc}") from exc


def post_form_json(url: str, data: dict[str, str], timeout: int = 45) -> dict[str, Any]:
    encoded = parse.urlencode(data).encode("utf-8")
    req = request.Request(url, data=encoded, headers={"Accept": "application/json"}, method="POST")
    try:
        with request.urlopen(req, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Provider API error {exc.code}: {body}") from exc
    except Exception as exc:
        raise RuntimeError(f"Provider API request failed: {exc}") from exc
