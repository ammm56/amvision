"""通用文本与文件 payload 校验 helper。"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import PurePosixPath

from backend.service.application.errors import InvalidRequestError


FILE_REF_REQUIRED_FIELDS = (
    "transport_kind",
    "storage_ref",
    "object_key",
    "file_name",
    "media_type",
    "content_length",
    "checksum_algorithm",
    "checksum",
    "immutable_version",
)


def require_text_payload(
    payload: object, *, field_name: str = "text"
) -> dict[str, object]:
    """校验并复制一份闭合的 text.v1 payload。"""

    if not isinstance(payload, Mapping):
        raise InvalidRequestError(f"{field_name} 必须是 text.v1 对象")
    allowed_fields = {"text", "media_type", "charset"}
    unexpected_fields = sorted(set(payload) - allowed_fields)
    if unexpected_fields:
        raise InvalidRequestError(
            f"{field_name} 包含 text.v1 未声明字段",
            details={"unexpected_fields": unexpected_fields},
        )
    text = payload.get("text")
    media_type = payload.get("media_type")
    charset = payload.get("charset")
    if not isinstance(text, str):
        raise InvalidRequestError(f"{field_name}.text 必须是字符串")
    if not isinstance(media_type, str) or not media_type.strip():
        raise InvalidRequestError(f"{field_name}.media_type 不能为空")
    if not isinstance(charset, str) or not charset.strip():
        raise InvalidRequestError(f"{field_name}.charset 不能为空")
    return {
        "text": text,
        "media_type": media_type.strip().lower(),
        "charset": charset.strip().lower(),
    }


def require_file_ref_payload(
    payload: object,
    *,
    field_name: str = "file",
) -> dict[str, object]:
    """校验并复制一份不含文件字节和绝对路径的 file-ref.v1 payload。"""

    if not isinstance(payload, Mapping):
        raise InvalidRequestError(f"{field_name} 必须是 file-ref.v1 对象")
    allowed_fields = {*FILE_REF_REQUIRED_FIELDS, "metadata"}
    unexpected_fields = sorted(set(payload) - allowed_fields)
    missing_fields = sorted(set(FILE_REF_REQUIRED_FIELDS) - set(payload))
    if missing_fields or unexpected_fields:
        raise InvalidRequestError(
            f"{field_name} 不是闭合的 file-ref.v1 payload",
            details={
                "missing_fields": missing_fields,
                "unexpected_fields": unexpected_fields,
            },
        )
    if payload.get("transport_kind") != "storage":
        raise InvalidRequestError(f"{field_name}.transport_kind 必须是 storage")
    if payload.get("storage_ref") != "object-store":
        raise InvalidRequestError(f"{field_name}.storage_ref 必须是 object-store")
    object_key = _require_non_empty_string(
        payload.get("object_key"), f"{field_name}.object_key"
    )
    normalized_path = PurePosixPath(object_key)
    if normalized_path.is_absolute() or ".." in normalized_path.parts:
        raise InvalidRequestError(f"{field_name}.object_key 不是安全的相对对象 key")
    content_length = payload.get("content_length")
    if (
        not isinstance(content_length, int)
        or isinstance(content_length, bool)
        or content_length < 0
    ):
        raise InvalidRequestError(f"{field_name}.content_length 必须是非负整数")
    if payload.get("checksum_algorithm") != "sha256":
        raise InvalidRequestError(f"{field_name}.checksum_algorithm 必须是 sha256")
    checksum = _require_non_empty_string(
        payload.get("checksum"), f"{field_name}.checksum"
    ).lower()
    if len(checksum) != 64 or any(
        character not in "0123456789abcdef" for character in checksum
    ):
        raise InvalidRequestError(f"{field_name}.checksum 必须是 64 位 SHA-256")
    metadata = payload.get("metadata")
    if metadata is not None and not isinstance(metadata, Mapping):
        raise InvalidRequestError(f"{field_name}.metadata 必须是对象")
    result: dict[str, object] = {
        "transport_kind": "storage",
        "storage_ref": "object-store",
        "object_key": object_key,
        "file_name": _require_non_empty_string(
            payload.get("file_name"), f"{field_name}.file_name"
        ),
        "media_type": _require_non_empty_string(
            payload.get("media_type"), f"{field_name}.media_type"
        ).lower(),
        "content_length": content_length,
        "checksum_algorithm": "sha256",
        "checksum": checksum,
        "immutable_version": _require_non_empty_string(
            payload.get("immutable_version"),
            f"{field_name}.immutable_version",
        ),
    }
    if metadata is not None:
        result["metadata"] = dict(metadata)
    return result


def require_file_refs_payload(
    payload: object,
    *,
    field_name: str = "files",
) -> dict[str, object]:
    """校验 file-refs.v1 的顺序、count 和每个 file-ref。"""

    if not isinstance(payload, Mapping) or set(payload) != {"items", "count"}:
        raise InvalidRequestError(f"{field_name} 必须是闭合的 file-refs.v1 对象")
    items = payload.get("items")
    count = payload.get("count")
    if not isinstance(items, list):
        raise InvalidRequestError(f"{field_name}.items 必须是数组")
    if not isinstance(count, int) or isinstance(count, bool) or count != len(items):
        raise InvalidRequestError(f"{field_name}.count 必须等于 items 长度")
    return {
        "items": [
            require_file_ref_payload(item, field_name=f"{field_name}.items[{index}]")
            for index, item in enumerate(items)
        ],
        "count": count,
    }


def _require_non_empty_string(value: object, field_name: str) -> str:
    """读取非空字符串并去除首尾空白。"""

    if not isinstance(value, str) or not value.strip():
        raise InvalidRequestError(f"{field_name} 不能为空")
    return value.strip()


__all__ = [
    "FILE_REF_REQUIRED_FIELDS",
    "require_file_ref_payload",
    "require_file_refs_payload",
    "require_text_payload",
]
