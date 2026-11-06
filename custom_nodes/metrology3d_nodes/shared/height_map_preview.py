"""高度图显示只传完整有界统计格，不传贡献成员，也不改变业务结果。"""

import base64
from hashlib import sha256

from backend.contracts.workflows.point_cloud import canonical_cloud_json
from custom_nodes.metrology3d_nodes.shared.height_map_reference import (
    resolve_height_map,
)
from custom_nodes.metrology3d_nodes.shared.height_map_assets import result_evidence
from backend.service.application.errors import InvalidRequestError


def height_map_base_policy(runtime, cloud, value, policy):
    """先给不可显示状态留出空间；不让附件超限提示再次突破正文预算。"""
    if value is None:
        return policy
    result = resolve_height_map(runtime, value, cloud=cloud)
    reserve = (
        max(
            len(
                canonical_cloud_json(
                    dict(height_map=dict(state="unavailable", reason=reason))
                )
            )
            for reason in (
                result.reason,
                "preview_size_limit",
                "preview_allocation_failed",
            )
            if reason is not None
        )
        + 1
    )
    if reserve >= policy.max_body_bytes:
        raise InvalidRequestError("高度图状态超过显示正文预算")
    return policy.model_copy(update={"max_body_bytes": policy.max_body_bytes - reserve})


def attach_height_map(runtime, cloud, body, value, *, policy, cancel):
    """复用点云显示正文和预算；超过完整格预算明确不可显示，不抽格补洞。"""
    if value is None:
        return body
    result = resolve_height_map(runtime, value, cloud=cloud)
    output = dict(body)
    if result.reason is not None:
        output["height_map"] = dict(state="unavailable", reason=result.reason)
        return output
    evidence = result_evidence(result, cloud)
    cells = evidence.parameters.cell_count()
    width = 4 if evidence.dtype == "float32" else 8
    length = cells * (width * 3 + 8)
    body_size = len(canonical_cloud_json(body))
    if (
        cells > policy.max_points
        or length + (body.get("data") or {}).get("content_length", 0)
        > policy.max_data_bytes
        or length * 12 + body_size * 2
        > min(policy.max_working_bytes, runtime.policy.max_working_bytes)
    ):
        output["height_map"] = dict(state="unavailable", reason="preview_size_limit")
        return output
    try:
        with result.borrow(runtime) as arrays:
            cancel()
            raw = b"".join(
                arrays[name].tobytes()
                for name in ("heights", "minimum", "maximum", "counts")
            )
            output["height_map"] = dict(
                format_id="amvision.height-map-preview.v1",
                state="ready",
                observation_id=cloud.observation_id,
                cloud_id=cloud.cloud_id,
                evidence=evidence.model_dump(mode="json"),
                data=dict(
                    encoding="base64",
                    content_length=len(raw),
                    checksum_algorithm="sha256",
                    checksum=sha256(raw).hexdigest(),
                    content=base64.b64encode(raw).decode("ascii"),
                ),
            )
            cancel()
        if len(canonical_cloud_json(output)) > policy.max_body_bytes:
            output["height_map"] = dict(
                state="unavailable", reason="preview_size_limit"
            )
    except MemoryError:
        output["height_map"] = dict(
            state="unavailable", reason="preview_allocation_failed"
        )
    return output
