"""MES HTTP 输出节点 HTTP 调用和响应解析。"""

from __future__ import annotations

import httpx

from custom_nodes.output_mes_http_nodes.backend.runtime.types import HttpMethod


def _build_response_payload(
    *,
    response: httpx.Response,
    url: str,
    method: HttpMethod,
    primary_source_kind: str,
) -> dict[str, object]:
    """构造 HTTP 回传结果摘要。"""

    payload: dict[str, object] = {
        "ok": response.is_success,
        "status_code": response.status_code,
        "url": url,
        "method": method,
        "primary_source_kind": primary_source_kind,
        "headers": {str(key): value for key, value in response.headers.items()},
    }
    response_json = _try_read_response_json(response)
    if response_json is not None:
        payload["body_json"] = response_json
    else:
        payload["body_text"] = response.text
    return payload


def _try_read_response_json(response: httpx.Response) -> object | None:
    """尝试从响应中读取 JSON。"""

    content_type = response.headers.get("content-type", "").lower()
    if "json" not in content_type:
        return None
    try:
        return response.json()
    except ValueError:
        return None
