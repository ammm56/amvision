"""配准接入当前 CloudRuntime；只借输入，不创建新的资源系统。"""

import numpy as np

from backend.contracts.workflows.geometry3d_methods import parameter_digest
from backend.contracts.workflows.geometry3d_observations import Pose3d
from backend.contracts.workflows.registration3d import (
    CoarseRegistrationSettings,
    DatumRegistrationSettings,
    RegistrationMethod,
    metric_units,
)
from backend.contracts.workflows.registration3d_search import RegistrationSearchEvidence
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
from custom_nodes.metrology3d_nodes.shared import coarse_registration
from custom_nodes.metrology3d_nodes.shared.datum_registration import (
    register_datum_arrays,
)
from custom_nodes.metrology3d_nodes.shared.pose_source import require_pose
from backend.contracts.workflows.frame3d_evidence import FramePoseEvidence
from backend.contracts.workflows.geometry3d_methods import FrameBuildMethod
from backend.contracts.workflows.registration3d_datum import DatumRegistrationEvidence


def register_cloud(
    runtime,
    source,
    reference,
    parameters,
    *,
    cancel,
    source_datum=None,
    reference_datum=None,
):
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
    coarse = isinstance(parameters, CoarseRegistrationSettings)
    planar = isinstance(parameters, DatumRegistrationSettings)
    frames = (source_datum, reference_datum)
    frame_evidence = None
    if planar:
        if any(f is None or not isinstance(f.method, FrameBuildMethod) for f in frames):
            raise InvalidRequestError("台面配准必须连接两路 Build Frame 位姿")
        for cloud, frame in zip((source, reference), frames, strict=True):
            require_pose(
                runtime,
                frame,
                observation_id=cloud.observation_id,
                frame_id=cloud.spatial.frame_id,
                length_unit=cloud.spatial.length_unit,
                cancel=cancel,
            )
        frame_evidence = tuple(
            FramePoseEvidence.model_validate(
                f.model_dump(include=set(FramePoseEvidence.model_fields))
            )
            for f in frames
        )
    elif any(f is not None for f in frames):
        raise InvalidRequestError("非台面模式不消费基准位姿，请移除无关接线")
    parents = tuple(
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
    )
    units = metric_units(parameters.length_unit, coarse=coarse, datum=planar)
    arrays = []
    normal_arrays = []
    search_evidence = (
        RegistrationSearchEvidence(feature_correspondence_count=0, candidates=())
        if coarse
        else None
    )
    normals = matrix = positions = block = correction = None
    try:
        datum_valid = not planar or all(
            f.state == "found" and f.quality.usable for f in frames
        )
        if any(c.state != "ready" for c in (source, reference)) or not datum_valid:
            values = {k: None for k in units}
            values.update(
                source_count=source.point_count,
                reference_count=reference.point_count,
                converged=0,
            )
            if coarse:
                values["candidate_consistency"] = 0
            if planar:
                values["datum_valid"] = int(datum_valid)
            reason = "upstream_unavailable"
        else:
            rows = runtime.policy.chunk_rows
            input_width = max(
                sum(np.dtype(f.dtype).itemsize * f.components for f in c.fields)
                for c in (source, reference)
            )
            required = (
                coarse_registration.working_bytes(
                    source.point_count, reference.point_count, rows, parameters.search
                )
                if coarse
                else working_bytes(source.point_count, reference.point_count, rows)
            )
            if required + rows * input_width * 2 > runtime.policy.max_working_bytes:
                raise InvalidRequestError("配准完整索引与工作数组超过工作预算")
            for index, cloud in enumerate((source, reference)):
                need_normals = coarse or (
                    index == 1 and parameters.algorithm == "point-to-plane"
                )
                if need_normals and "normals" not in {f.name for f in cloud.fields}:
                    raise InvalidRequestError(
                        "配准方法缺少所需法向，请连接 Estimate Normals"
                    )
                positions = np.empty((cloud.point_count, 3), dtype=np.float64)
                arrays.append(positions)
                if need_normals:
                    normals = np.empty_like(positions)
                else:
                    normals = None
                normal_arrays.append(normals)
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
                                    "配准输入有无效法向，不能静默丢弃支持"
                                )
                            normals[start:stop] = block["normals"]
                            if (
                                coarse
                                and "normal_oriented" in block
                                and not block["normal_oriented"].all()
                            ):
                                raise InvalidRequestError(
                                    "特征配准需要明确有向法向，不能静默翻转或删除"
                                )
                    block = None
            if coarse:
                matrix, values, reason, search_evidence = (
                    coarse_registration.coarse_register_arrays(
                        *arrays,
                        *normal_arrays,
                        parameters,
                        observation_id=source.observation_id,
                        max_working_bytes=runtime.policy.max_working_bytes,
                        chunk_rows=rows,
                        cancel=cancel,
                    )
                )
            elif planar:
                matrix, values, reason, correction = register_datum_arrays(
                    *arrays,
                    normal_arrays[1],
                    parameters,
                    frame_evidence,
                    max_working_bytes=runtime.policy.max_working_bytes,
                    chunk_rows=rows,
                    cancel=cancel,
                )
            else:
                matrix, values, reason = register_arrays(
                    *arrays,
                    normal_arrays[1],
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
            correction = None
            reason = reason or "quality_failed"
        method = RegistrationMethod(
            scope="feature-se3" if coarse else "datum-se2" if planar else "local-se3",
            parameters=parameters,
            parameters_sha256=parameter_digest(parameters),
            parents=parents,
            search=search_evidence,
            datum=None
            if not planar
            else DatumRegistrationEvidence(
                frames=frame_evidence,
                correction=None if correction is None else correction.tolist(),
            ),
        )
        state = (
            "found"
            if matrix is not None
            else "ambiguous"
            if reason == "ambiguous_candidates"
            else "not_found"
            if reason in {"no_overlap", "upstream_unavailable"}
            else "underconstrained"
            if reason
            in {
                "insufficient_support",
                "degenerate_support",
                "insufficient_feature_matches",
            }
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
            support=(source, reference)
            + (() if not planar else tuple(s for f in frames for s in f.support)),
            reference_feature_ids=method.feature_ids(),
        )
    except BaseException as error:
        arrays.clear()
        normal_arrays.clear()
        normals = matrix = positions = block = correction = None
        release_exception_frames(error)
        raise
