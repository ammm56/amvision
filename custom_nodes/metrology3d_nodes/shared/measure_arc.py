"""圆弧测量在现有 Scope 内借用支持，不新增点云或再次拟圆。"""

from hashlib import sha256

from backend.contracts.workflows.arc3d_evidence import ArcGeometry
from backend.contracts.workflows.dimension3d_parameters import dimension_metric_units
from backend.service.application.errors import InvalidRequestError
from backend.service.application.runtime.exception_cleanup import (
    release_exception_frames,
)
from custom_nodes.metrology3d_nodes.shared.arc_measurement import analyze_arc
from custom_nodes.metrology3d_nodes.shared.boundary_runtime import materialize_positions
from custom_nodes.metrology3d_nodes.shared.dimension_runtime import (
    dimension_evaluation,
    dimension_result,
    dimension_support,
    select_features,
)


def measure_arc(runtime, groups, parameters, *, cancel):
    """异常回收沿既有边界，外部保存异常也不能保留物化数组。"""
    try:
        return _measure_arc(runtime, groups, parameters, cancel=cancel)
    except BaseException as error:
        release_exception_frames(error)
        raise


def _measure_arc(runtime, groups, parameters, *, cancel):
    """原圆支持和质量全部保留；选段仅作用于圆弧量值。"""
    circle = select_features(
        runtime, groups, parameters, [parameters.feature_id], "circle"
    )[0]
    support = dimension_support(
        runtime, circle.support, "source", feature=circle, cancel=cancel
    )
    evaluation, _ = dimension_evaluation(parameters, circle)
    reason, stage, geometry = circle.reason, "input", None
    metrics = {
        key: (None, unit)
        for key, unit in dimension_metric_units(parameters).items()
        if key != "geometry_usable"
    }
    metrics.update({m.item_id: (m.value, m.unit) for m in circle.quality.metrics.items})
    if circle.valid:
        positions, _ = materialize_positions(
            runtime, circle.support, factor=1024, cancel=cancel
        )
        try:
            analysis = analyze_arc(
                positions,
                circle.support.topology,
                circle.geometry,
                evaluation,
                parameters.selection,
                parameters.mode,
                maximum_step=circle.method.parameters.max_arc_step,
                max_working_bytes=runtime.policy.max_working_bytes,
                cancel=cancel,
            )
        except ValueError as error:
            raise InvalidRequestError(str(error)) from error
        finally:
            positions = None
        reason, stage = analysis.reason, "support"
        if reason is None:
            values = analysis.geometry
            with runtime.borrow(circle.support) as view:
                for key in ("start", "end"):
                    endpoint = values[key]
                    if endpoint is None:
                        continue
                    cancel()
                    row = endpoint["vertex_index"]
                    endpoint.update(source_index=None, lineage=None)
                    if circle.support.vertex_kind == "source":
                        endpoint["source_index"] = int(
                            view.source_indices(row, row + 1).reshape(-1)[0]
                        )
                    else:
                        block = view.lineage_chunk(row, row + 1)
                        endpoint["lineage"] = dict(
                            source_edge=tuple(int(i) for i in block["source_edges"][0]),
                            weights=block["weights"][0],
                            source_face_count=len(block["source_faces"]),
                            source_faces_sha256=sha256(
                                block["source_faces"].tobytes()
                            ).hexdigest(),
                        )
            geometry = ArcGeometry.model_validate(values)
            for key, value in dict(
                selected_point_count=sum(p.point_count for p in geometry.parts),
                selected_segment_count=len(geometry.parts),
                coverage_angle=geometry.coverage_angle,
                overlap_angle=geometry.overlap_angle,
                polyline_length=geometry.polyline_length,
            ).items():
                metrics[key] = (value, metrics[key][1])
    cancel()
    return dimension_result(
        "measure-arc",
        parameters,
        groups[0].observation_id,
        (support,),
        geometry=geometry,
        metrics=metrics,
        values=geometry.values() if geometry else {},
        reason=reason,
        stage=stage,
        feature_id=circle.feature_id if reason else None,
        evaluation=evaluation,
    )
