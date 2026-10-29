"""只标注已有有界显示点；原始行号与坐标双重匹配，不能误染另一分支。"""

import base64

import numpy as np

from backend.contracts.workflows.geometry3d_preview import PlaneSamples
from backend.service.application.errors import InvalidRequestError


def plane_samples(runtime, cloud, body, feature, *, policy, held_bytes, cancel):
    """来源不同或未显示的点保持无关，不将 ROI 外点叫作拟合剔除点。"""
    if body["state"] != "ready" or feature.support.state != "ready":
        return None
    if cloud.vertex_kind != "source" or feature.support.vertex_kind != "source":
        return None
    root, _ = runtime.original_source(cloud)
    other, _ = runtime.original_source(feature.support)
    if root.cloud_id != other.cloud_id:
        return None
    n = body["display_point_count"]
    data = body["data"]
    working = min(policy.max_working_bytes, runtime.policy.max_working_bytes)
    held = held_bytes + data["content_length"] + n * 128
    if held >= working:
        raise MemoryError("preview_size_limit")
    raw = base64.b64decode(data["content"], validate=True)
    fields = {f["name"]: f for f in data["fields"]}
    xyz = np.ndarray(
        (n, 3),
        dtype=np.dtype(fields["positions"]["dtype"]).newbyteorder("<"),
        buffer=raw,
        offset=fields["positions"]["offset"],
    )
    indices = np.ndarray(
        n, dtype="<u8", buffer=raw, offset=fields["source_indices"]["offset"]
    )
    classes, residuals = np.zeros(n, dtype=np.uint8), [None] * n
    display_order = np.argsort(indices, kind="stable")
    sorted_indices = indices[display_order]
    method = feature.support.provenance.method
    parent = (
        runtime.parent_reference(feature.support)
        if method and method.method_id == "fit-plane-support"
        else None
    )
    for reference, kind in ([(parent, 2)] if parent is not None else []) + [
        (feature.support, 1)
    ]:
        width = sum(np.dtype(f.dtype).itemsize * f.components for f in reference.fields)
        rows = min(runtime.policy.chunk_rows, (working - held) // (width * 2 + 128))
        if rows < 1:
            raise MemoryError("preview_size_limit")
        with runtime.borrow(reference) as view:
            for start in range(0, reference.point_count, rows):
                cancel()
                stop = min(start + rows, reference.point_count)
                source = view.source_indices(start, stop).reshape(-1)
                if not len(source):
                    continue
                # 两侧均可为有序边界，不能再假设原始行号递增。
                source_order = np.argsort(source, kind="stable")
                sorted_source = source[source_order]
                locations = np.searchsorted(sorted_source, sorted_indices)
                inside = locations < len(source)
                display_rows = display_order[inside]
                locations = source_order[locations[inside]]
                matched = source[locations] == indices[display_rows]
                display_rows, locations = display_rows[matched], locations[matched]
                if not len(display_rows):
                    continue
                points = view.chunk(start, stop)["positions"][locations]
                if not np.isfinite(points).all():
                    raise InvalidRequestError("平面显示支持包含非法位置")
                matching = np.all(points == xyz[display_rows], axis=1)
                display_rows, points = display_rows[matching], points[matching]
                classes[display_rows] = kind
                if feature.valid:
                    with np.errstate(over="raise", invalid="raise"):
                        values = (
                            np.asarray(points, dtype=np.float64)
                            @ np.asarray(feature.geometry.normal)
                            + feature.geometry.offset
                        )
                    for index, value in zip(display_rows, values):
                        residuals[int(index)] = float(value)
    cancel()
    return PlaneSamples(
        data_sha256=data["checksum"], classes=classes.tolist(), residuals=residuals
    )
