"""全量候选扫描、确定性抽样及独立有界显示副本，不持有原云 lease。"""

import base64
from hashlib import sha256
import numpy as np

from backend.contracts.workflows.point_cloud import FIELD_WIDTHS
from backend.contracts.workflows.point_cloud import canonical_cloud_json
from backend.contracts.workflows.point_cloud_preview import CloudPreviewOptions
from backend.service.application.errors import InvalidRequestError


def unavailable_body(reference, reason):
    """显示失败与业务 unavailable 都不伪造点数或云身份。"""
    return dict(
        type="point-cloud-preview",
        format_id="amvision.point-cloud-preview.v2",
        state="unavailable",
        reason=reason,
        observation_id=reference.observation_id,
        cloud_id=None,
        revision=None,
        spatial=reference.spatial.model_dump(mode="json"),
        source_point_count=None,
        point_count=None,
        vertex_kind=None,
        display_point_count=None,
        excluded_non_finite_count=None,
        sampling=None,
        bounds=None,
        render_origin=None,
        data=None,
        color=None,
        source_asset=None,
    )


def build_cloud_preview(runtime, reference, options, *, policy, cancel):
    """显示分配失败只交付显示错误，不改变其他节点的业务结果。"""
    try:
        return _build_cloud_preview(
            runtime, reference, options, policy=policy, cancel=cancel
        )
    except MemoryError:
        return unavailable_body(reference, "preview_allocation_failed")


def _build_cloud_preview(runtime, reference, options, *, policy, cancel):
    """有界多遍扫描；原始行号来自可信运行记录，不能由当前点数推断。"""
    options = CloudPreviewOptions.model_validate(options)
    if options.point_limit > policy.max_points:
        raise InvalidRequestError("显示点数超过显式策略")
    if reference.run_id != runtime.run_id:
        raise InvalidRequestError("点云不属于当前运行")
    if reference.state == "unavailable":
        return unavailable_body(reference, reference.reason)
    fields = {f.name: f for f in reference.fields}
    color = options.color
    if color.mode == "rgb" and "colors" not in fields:
        raise InvalidRequestError("RGB 显示需要 colors 字段")
    if color.mode == "scalar" and (
        color.field not in fields or color.component >= fields[color.field].components
    ):
        raise InvalidRequestError("显示标量字段或分量无效")
    row_bytes = sum(FIELD_WIDTHS[f.dtype] * f.components for f in fields.values())
    rows = min(
        runtime.policy.chunk_rows,
        runtime.policy.max_working_bytes // (row_bytes + 64),
        policy.max_working_bytes // (row_bytes + 64),
    )
    if rows < 1:
        return unavailable_body(reference, "preview_size_limit")
    with runtime.borrow(reference) as view:
        count = excluded = 0
        for start in range(0, reference.point_count, rows):
            cancel()
            block = view.chunk(start, min(start + rows, reference.point_count))
            valid, non_finite = _valid(block)
            count += int(np.count_nonzero(valid))
            excluded += non_finite
        shown = min(count, options.point_limit)
        layout = [
            ("positions", fields["positions"].dtype, 3),
            (
                "source_indices"
                if reference.vertex_kind == "source"
                else "vertex_indices",
                "uint64",
                1,
            ),
        ]
        if color.mode == "rgb":
            layout.append(("colors", "uint8", 3))
        elif color.mode == "scalar":
            layout.append(("scalar", fields[color.field].dtype, 1))
        descriptors, length = [], 0
        for name, dtype, components in layout:
            width = FIELD_WIDTHS[dtype]
            length = (length + width - 1) // width * width
            size = shown * components * width
            descriptors.append(
                dict(
                    name=name,
                    dtype=dtype,
                    components=components,
                    count=shown,
                    offset=length,
                    byte_length=size,
                )
            )
            length += size
        # bytearray、base64 bytes/str、精确采样序号和当前块都必须有预算。
        work = (
            length
            + 4 * (4 * ((length + 2) // 3))
            + shown * 24
            + rows * (row_bytes + 64)
        )
        if length > policy.max_data_bytes or work > policy.max_working_bytes:
            return unavailable_body(reference, "preview_size_limit")
        body = dict(
            type="point-cloud-preview",
            format_id="amvision.point-cloud-preview.v2",
            state="ready" if shown else "empty",
            reason=None,
            observation_id=reference.observation_id,
            cloud_id=reference.cloud_id,
            revision=reference.revision,
            spatial=reference.spatial.model_dump(mode="json"),
            source_point_count=runtime.source_point_count(reference),
            point_count=reference.point_count,
            vertex_kind=reference.vertex_kind,
            display_point_count=shown,
            excluded_non_finite_count=excluded,
            sampling=dict(
                method_id="logical-index-uniform-v1",
                requested_limit=options.point_limit,
            ),
            bounds=None,
            render_origin=None,
            data=None,
            color=dict(mode=color.mode),
            source_asset=reference.source.reference.model_dump(mode="json")
            if reference.source.kind == "asset"
            else None,
        )
        if not shown:
            if color.mode == "scalar":
                body["color"].update(
                    field=color.field,
                    component=color.component,
                    min=None,
                    max=None,
                    invalid_count=0,
                )
            return (
                body
                if len(canonical_cloud_json(body)) <= policy.max_body_bytes
                else unavailable_body(reference, "preview_size_limit")
            )
        raw = bytearray(length)
        arrays = {
            d["name"]: np.ndarray(
                (shown, d["components"]),
                dtype=np.dtype(d["dtype"]).newbyteorder("<"),
                buffer=raw,
                offset=d["offset"],
            )
            for d in descriptors
        }
        # 用 Python 整数计算乘积，避免 K/M 合法但 uint64 中间乘积溢出。
        targets = np.fromiter(
            (j * (count - 1) // (shown - 1) if shown > 1 else 0 for j in range(shown)),
            dtype=np.uint64,
            count=shown,
        )
        seen = written = 0
        for start in range(0, reference.point_count, rows):
            cancel()
            stop = min(start + rows, reference.point_count)
            block = view.chunk(start, stop)
            valid, _ = _valid(block)
            candidates = np.flatnonzero(valid)
            end = int(np.searchsorted(targets, seen + len(candidates), side="left"))
            selected = candidates[(targets[written:end] - seen).astype(np.intp)]
            if len(selected):
                arrays["positions"][written:end] = block["positions"][selected]
                if reference.vertex_kind == "source":
                    arrays["source_indices"][written:end, 0] = view.source_indices(
                        start, stop
                    )[selected]
                else:
                    arrays["vertex_indices"][written:end, 0] = start + selected
                if color.mode == "rgb":
                    arrays["colors"][written:end] = block["colors"][selected]
                elif color.mode == "scalar":
                    arrays["scalar"][written:end, 0] = block[color.field][
                        selected, color.component
                    ]
            written, seen = end, seen + len(candidates)
        if written != shown:
            raise InvalidRequestError("显示候选在扫描期间发生变化")
        low, high = arrays["positions"].min(axis=0), arrays["positions"].max(axis=0)
        body["bounds"] = dict(min=low.tolist(), max=high.tolist())
        body["render_origin"] = (
            low.astype(np.float64) / 2 + high.astype(np.float64) / 2
        ).tolist()
        if color.mode == "scalar":
            scalar = arrays["scalar"][:, 0]
            finite = scalar[np.isfinite(scalar)]
            limits = (
                (color.range.min, color.range.max)
                if color.range.mode == "fixed"
                else (
                    (_number(finite.min()), _number(finite.max()))
                    if len(finite)
                    else (None, None)
                )
            )
            body["color"].update(
                field=color.field,
                component=color.component,
                min=limits[0],
                max=limits[1],
                invalid_count=shown - len(finite),
            )
        body["data"] = dict(
            encoding="base64",
            content_length=length,
            checksum_algorithm="sha256",
            checksum=sha256(raw).hexdigest(),
            fields=descriptors,
            content=base64.b64encode(raw).decode("ascii"),
        )
        cancel()
        if len(canonical_cloud_json(body)) > policy.max_body_bytes:
            return unavailable_body(reference, "preview_size_limit")
        return body


def _valid(block):
    """显示仅选择有效且 XYZ 有限的点，不把无效位置映射为零。"""
    finite = np.isfinite(block["positions"]).all(axis=1)
    valid = (
        finite if "validity" not in block else finite & (block["validity"][:, 0] != 0)
    )
    return valid, int(np.count_nonzero(~finite))


def _number(value):
    """色标保留整数精度和浮点 round-trip 文本。"""
    return str(int(value)) if value.dtype.kind in "iu" else repr(float(value))
