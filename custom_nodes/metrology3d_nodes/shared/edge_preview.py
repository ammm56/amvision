"""必要诊断沿既有显示正文传输；完整记录超预算时明确不可显示，不抽成功点。"""

import base64
from hashlib import sha256

import numpy as np

from backend.contracts.workflows.point_cloud import canonical_cloud_json
from backend.service.application.errors import InvalidRequestError
from custom_nodes.metrology3d_nodes.shared.edge_assets import StoredEdgeResult
from custom_nodes.metrology3d_nodes.shared.edge_reference import resolve_edge_diagnostic


# 固定 LE 紧凑记录，浏览器按同一偏移读取；不建立新的运行资源系统。
RECORD = np.dtype(
    [
        ("position", "<f8", (3,)),
        ("source", "<u8"),
        ("status", "u1"),
        ("side", "u1"),
        ("context", "u1"),
        ("candidate", "u1"),
        ("partner", "<i8"),
        ("metrics", "<f8", (3,)),
    ]
)


def edge_base_policy(runtime, cloud, value, policy):
    """为不可显示状态预留正文空间，先验证引用而不是悄悄忽略错分支。"""
    if value is None:
        return policy
    resolve_edge_diagnostic(runtime, value, cloud=cloud)
    size = (
        len(
            canonical_cloud_json(
                {
                    "edge_diagnostics": {
                        "state": "unavailable",
                        "reason": "preview_allocation_failed",
                    }
                }
            )
        )
        + 1
    )
    if size >= policy.max_body_bytes:
        raise InvalidRequestError("边诊断状态超过显示正文预算")
    return policy.model_copy(update={"max_body_bytes": policy.max_body_bytes - size})


def attach_edge_diagnostic(runtime, cloud, body, value, *, policy, cancel):
    """显示完整配对/逐点状态，来源仍由现有保存资产负责长期追溯。"""
    if value is None:
        return body
    ref, edge, sampling = resolve_edge_diagnostic(runtime, value, cloud=cloud)
    output = dict(body)
    output["edge_diagnostics"] = {
        "state": "unavailable",
        "reason": "preview_size_limit",
    }
    count = (ref.edge.record_count if edge is not None else 0) + (
        cloud.point_count if sampling is not None else 0
    )
    length = count * RECORD.itemsize
    existing_bytes = sum(
        (body.get(key) or {}).get("data", {}).get("content_length", 0)
        for key in ("height_map",)
    ) + (body.get("data") or {}).get("content_length", 0)
    if (
        count > policy.max_points
        or length + existing_bytes > policy.max_data_bytes
        or length * 12 + len(canonical_cloud_json(body)) * 2
        > min(policy.max_working_bytes, runtime.policy.max_working_bytes)
    ):
        return output
    try:
        sections = []
        if edge is not None:
            with edge.borrow(runtime) as raw:
                if isinstance(edge, StoredEdgeResult):
                    pairs = raw["pairs"]
                    sections.append(_edge_records(pairs, ref.edge))
                else:
                    with edge.chains.pairs.borrow(runtime) as pairs:
                        sections.append(_edge_records(pairs, ref.edge))
        if sampling is not None:
            with (
                sampling.borrow(runtime) as (candidates, context),
                runtime.borrow(cloud) as view,
            ):
                records = np.zeros(cloud.point_count, dtype=RECORD)
                records["partner"] = -1
                records["metrics"] = np.nan
                records["side"] = 255
                for start in range(0, cloud.point_count, runtime.policy.chunk_rows):
                    cancel()
                    stop = min(cloud.point_count, start + runtime.policy.chunk_rows)
                    records["position"][start:stop] = view.chunk(start, stop)[
                        "positions"
                    ]
                for destination, source in (
                    ("source", "identity_rows"),
                    ("status", "status"),
                    ("candidate", "candidate"),
                ):
                    records[destination] = candidates[source].reshape(-1)
                records["context"] = context["context"].reshape(-1)
                sections.append(records.tobytes())
        cancel()
        raw = b"".join(sections)
        preview = dict(
            format_id="amvision.edge-preview.v1",
            state="ready",
            observation_id=cloud.observation_id,
            cloud_id=cloud.cloud_id,
            edge=ref.edge.model_dump(mode="json") if ref.edge else None,
            sampling=ref.sampling.model_dump(mode="json") if ref.sampling else None,
            data=dict(
                encoding="base64",
                content_length=len(raw),
                checksum_algorithm="sha256",
                checksum=sha256(raw).hexdigest(),
                content=base64.b64encode(raw).decode("ascii"),
            ),
        )
        if (
            len(canonical_cloud_json(dict(body, edge_diagnostics=preview)))
            <= policy.max_body_bytes
        ):
            output["edge_diagnostics"] = preview
        cancel()
    except MemoryError:
        output["edge_diagnostics"] = {
            "state": "unavailable",
            "reason": "preview_allocation_failed",
        }
    return output


def _edge_records(pairs, evidence):
    """只编码现有逐点证据，不改变配对或质量。"""
    records = np.zeros(evidence.record_count, dtype=RECORD)
    for target, source in (
        ("position", "positions"),
        ("source", "source_rows"),
        ("status", "status"),
        ("side", "sides"),
        ("partner", "partners"),
        ("metrics", "metrics"),
    ):
        records[target] = pairs[source].reshape(records[target].shape)
    if evidence.method.kind == "height-jump":
        records["position"] = records["position"] @ np.asarray(
            evidence.evaluation.rotation
        ).T + np.asarray(evidence.evaluation.origin)
    return records.tobytes()
