"""图片来源身份的通用构造与一致性校验。"""

from __future__ import annotations

from backend.service.application.errors import InvalidRequestError


IMAGE_IDENTITY_FORMAT_ID = "amvision.image-identity.v1"


def build_image_identity(
    image_payload: dict[str, object],
    *,
    width: int | None = None,
    height: int | None = None,
) -> dict[str, object]:
    """构造不包含 locator、可跨节点传递的图片身份。"""

    resolved_width = _require_positive_dimension(
        width if width is not None else image_payload.get("width"),
        field_name="width",
    )
    resolved_height = _require_positive_dimension(
        height if height is not None else image_payload.get("height"),
        field_name="height",
    )
    identity: dict[str, object] = {
        "format_id": IMAGE_IDENTITY_FORMAT_ID,
        "width": resolved_width,
        "height": resolved_height,
    }
    content_sha256 = image_payload.get("content_sha256")
    if isinstance(content_sha256, str) and content_sha256.strip():
        identity["content_sha256"] = content_sha256.strip().lower()
    return identity


def require_image_identity(
    value: object,
    *,
    field_name: str,
    node_id: str | None = None,
) -> dict[str, object]:
    """校验图片身份对象，不允许混入临时图片 locator。"""

    if not isinstance(value, dict):
        raise InvalidRequestError(
            f"{field_name} 必须是图片身份对象",
            details={"node_id": node_id},
        )
    if value.get("format_id") != IMAGE_IDENTITY_FORMAT_ID:
        raise InvalidRequestError(
            f"{field_name}.format_id 必须是 {IMAGE_IDENTITY_FORMAT_ID}",
            details={"node_id": node_id},
        )
    identity = build_image_identity(value)
    content_sha256 = value.get("content_sha256")
    if content_sha256 is not None:
        if not isinstance(content_sha256, str) or not content_sha256.strip():
            raise InvalidRequestError(
                f"{field_name}.content_sha256 必须是非空字符串",
                details={"node_id": node_id},
            )
        identity["content_sha256"] = content_sha256.strip().lower()
    return identity


def require_matching_image_identity(
    expected: dict[str, object],
    actual: dict[str, object],
    *,
    field_name: str,
    node_id: str | None = None,
) -> str:
    """要求尺寸一致，并在双方均有 SHA-256 时要求内容一致。"""

    for dimension in ("width", "height"):
        if expected.get(dimension) != actual.get(dimension):
            raise InvalidRequestError(
                f"{field_name} 与目标图片的 {dimension} 不一致",
                details={
                    "node_id": node_id,
                    "expected": expected.get(dimension),
                    "actual": actual.get(dimension),
                },
            )
    expected_sha = expected.get("content_sha256")
    actual_sha = actual.get("content_sha256")
    if isinstance(expected_sha, str) and isinstance(actual_sha, str):
        if expected_sha != actual_sha:
            raise InvalidRequestError(
                f"{field_name} 与目标图片的 content_sha256 不一致",
                details={
                    "node_id": node_id,
                    "expected": expected_sha,
                    "actual": actual_sha,
                },
            )
        return "content-sha256"
    return "dimensions"


def _require_positive_dimension(value: object, *, field_name: str) -> int:
    """读取图片身份中的正整数尺寸。"""

    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise InvalidRequestError(f"图片身份 {field_name} 必须是正整数")
    return int(value)
