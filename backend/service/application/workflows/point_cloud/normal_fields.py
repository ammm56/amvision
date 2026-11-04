"""法向字段校验及当前空间更新，复用现有点云注册和资产读取。"""

import numpy as np

from backend.contracts.workflows.cloud_normal_info import CloudNormalInfo
from backend.contracts.workflows.geometry3d import ORTHOGONAL_TOLERANCE
from backend.service.application.errors import InvalidRequestError


def derived_normal_info(parent, method):
    """原计算身份保持不变，只更新当前空间中的参考方向或观测点。"""
    if method.method_id == "estimate-normals":
        return CloudNormalInfo(
            method=method,
            support={
                name: getattr(parent, name)
                for name in ("run_id", "observation_id", "cloud_id", "revision")
            },
            frame_id=parent.spatial.frame_id,
            length_unit=parent.spatial.length_unit,
            orientation=method.parameters.orientation,
        )
    info = parent.normal_info
    if info is None:
        return None
    raw = info.model_dump(mode="json")
    orientation = raw["orientation"]
    if method.method_id == "transform-cloud":
        transform = method.parameters.transform
        matrix = np.asarray(transform.matrix, dtype=np.float64)
        raw["frame_id"] = transform.target_frame_id
        if orientation["kind"] == "direction":
            orientation["direction"] = (
                matrix[:3, :3] @ orientation["direction"]
            ).tolist()
        elif orientation["kind"] == "viewpoint":
            orientation["position"] = (
                matrix[:3, :3] @ orientation["position"] + matrix[:3, 3]
            ).tolist()
    elif method.method_id == "normalize-units":
        scale = {"m": 1000.0, "mm": 1.0, "um": 0.001}[info.length_unit]
        raw["length_unit"] = "mm"
        if orientation["kind"] == "viewpoint":
            orientation["position"] = (
                np.asarray(orientation["position"]) * scale
            ).tolist()
    return CloudNormalInfo.model_validate(raw)


def validate_normal_arrays(arrays, info, *, chunk_rows, cancel):
    """有界验证数值与状态，不把零占位当作有效法向，也不改变数组。"""
    if info is None:
        return
    count = len(arrays["normals"])
    tolerance = max(
        64 * np.finfo(arrays["normals"].dtype).eps, 2 * ORTHOGONAL_TOLERANCE
    )
    for start in range(0, count, chunk_rows):
        cancel()
        stop = min(count, start + chunk_rows)
        normals = arrays["normals"][start:stop]
        valid, oriented, reason = (
            arrays[name][start:stop, 0]
            for name in ("normal_valid", "normal_oriented", "normal_reason")
        )
        good = valid == 1
        signed = oriented == 1
        if (
            not np.isfinite(normals).all()
            or np.any(valid > 1)
            or np.any(oriented > 1)
            or np.any(reason > 5)
            or np.any(signed & ~good)
            or np.any(good != ((reason == 0) | (reason == 5)))
            or np.any((reason == 5) & signed)
            or np.any(normals[~good] != 0)
            or np.any(
                np.abs(np.linalg.norm(normals[good].astype(np.float64), axis=1) - 1)
                > tolerance
            )
        ):
            raise InvalidRequestError("计算法向数组与有效性状态不一致")
        if info.orientation.kind == "unoriented":
            if np.any(signed) or np.any(reason == 5):
                raise InvalidRequestError("无符号法向不能声明已定向或定向失败")
        elif np.any(good & ((reason == 0) != signed)):
            raise InvalidRequestError("有符号法向原因与定向状态不一致")
        if info.method.parameters.diagnostics:
            for name, maximum in (
                ("normal_rms", np.inf),
                ("normal_gap", 1),
                ("normal_variation", 1 / 3),
            ):
                values = arrays[name][start:stop, 0]
                if (
                    not np.isfinite(values).all()
                    or np.any(values < 0)
                    or np.any(values > maximum + tolerance)
                ):
                    raise InvalidRequestError("法向诊断字段超出合法数值范围")
