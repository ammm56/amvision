"""配准接入当前 CloudRuntime；只借输入，不创建新的资源系统。"""

import numpy as np

from backend.contracts.workflows.geometry3d_methods import parameter_digest
from backend.contracts.workflows.geometry3d_observations import Pose3d
from backend.contracts.workflows.registration3d import RegistrationMethod, metric_units
from backend.service.application.errors import InvalidRequestError
from backend.service.application.runtime.exception_cleanup import (
    release_exception_frames,
)
from custom_nodes.metrology3d_nodes.shared.cloud_assets import freeze_cloud_parent
from custom_nodes.metrology3d_nodes.shared.geometry_quality import geometry_quality
from custom_nodes.metrology3d_nodes.shared.registration import (
    register_arrays,
    working_bytes,
)


def register_cloud(runtime, source, reference, parameters, *, cancel):
    """source 与 reference 可来自不同观测，但必须同次 Run、已声明坐标和单位。"""
    cancel()
    for cloud, frame in (
        (source, parameters.source_frame_id),
        (reference, parameters.target_frame_id),
    ):
        if (cloud.run_id, cloud.spatial.frame_id, cloud.spatial.length_unit) != (
            runtime.run_id,
            frame,
            parameters.length_unit,
        ):
            raise InvalidRequestError("配准输入运行、坐标或单位与参数不一致")
    method = RegistrationMethod(
        parameters=parameters,
        parameters_sha256=parameter_digest(parameters),
        parents=tuple(
            dict(
                observation_id=c.observation_id,
                frame_id=c.spatial.frame_id,
                length_unit=c.spatial.length_unit,
                point_count=c.point_count,
                support_content_sha256=freeze_cloud_parent(runtime, c)["content_sha256"]
                if c.state == "ready"
                else None,
            )
            for c in (source, reference)
        ),
    )
    units = metric_units(parameters.length_unit)
    arrays = []
    normals = matrix = positions = block = None
    try:
        if any(c.state != "ready" for c in (source, reference)):
            values = {k: None for k in units}
            values.update(
                source_count=source.point_count,
                reference_count=reference.point_count,
                converged=0,
            )
            reason = "upstream_unavailable"
        else:
            rows = runtime.policy.chunk_rows
            input_width = max(
                sum(np.dtype(f.dtype).itemsize * f.components for f in c.fields)
                for c in (source, reference)
            )
            if (
                working_bytes(source.point_count, reference.point_count, rows)
                + rows * input_width * 2
                > runtime.policy.max_working_bytes
            ):
                raise InvalidRequestError("配准完整索引与工作数组超过工作预算")
            for index, cloud in enumerate((source, reference)):
                need_normals = index == 1 and parameters.algorithm == "point-to-plane"
                if need_normals and "normals" not in {f.name for f in cloud.fields}:
                    raise InvalidRequestError(
                        "点到面配准缺少参考法向，请连接 Estimate Normals"
                    )
                positions = np.empty((cloud.point_count, 3), dtype=np.float64)
                arrays.append(positions)
                if need_normals:
                    normals = np.empty_like(positions)
                with runtime.borrow(cloud) as view:
                    for start in range(0, cloud.point_count, rows):
                        cancel()
                        stop = min(start + rows, cloud.point_count)
                        block = view.chunk(start, stop)
                        if "validity" in block and not block["validity"].all():
                            raise InvalidRequestError(
                                "配准输入有无效点，请先执行 Filter Valid"
                            )
                        positions[start:stop] = block["positions"]
                        if need_normals:
                            if (
                                "normal_valid" in block
                                and not block["normal_valid"].all()
                            ):
                                raise InvalidRequestError(
                                    "参考云有无效法向，不能静默丢弃支持"
                                )
                            normals[start:stop] = block["normals"]
                    block = None
            matrix, values, reason = register_arrays(
                *arrays,
                normals,
                parameters,
                max_working_bytes=runtime.policy.max_working_bytes,
                chunk_rows=rows,
                cancel=cancel,
            )
        quality = geometry_quality(
            source.observation_id,
            {k: (values[k], u) for k, u in units.items()},
            parameters.quality_policy,
            reason=reason or "unavailable",
        )
        if not quality.usable:
            matrix = None
            reason = reason or "quality_failed"
        state = (
            "found"
            if matrix is not None
            else "not_found"
            if reason in {"no_overlap", "upstream_unavailable"}
            else "underconstrained"
            if reason in {"insufficient_support", "degenerate_support"}
            else "insufficient_quality"
        )
        transform = (
            None
            if matrix is None
            else dict(
                observation_id=source.observation_id,
                source_frame_id=parameters.source_frame_id,
                target_frame_id=parameters.target_frame_id,
                length_unit=parameters.length_unit,
                matrix=matrix.tolist(),
                provenance=dict(method=method, quality=quality),
            )
        )
        cancel()
        return Pose3d(
            run_id=runtime.run_id,
            pose_id=parameters.pose_id,
            observation_id=source.observation_id,
            source_frame_id=parameters.source_frame_id,
            target_frame_id=parameters.target_frame_id,
            length_unit=parameters.length_unit,
            state=state,
            reason=reason,
            transform=transform,
            method=method,
            quality=quality,
            support=(source, reference),
            reference_feature_ids=method.feature_ids(),
        )
    except BaseException as error:
        arrays.clear()
        normals = matrix = positions = block = None
        release_exception_frames(error)
        raise
