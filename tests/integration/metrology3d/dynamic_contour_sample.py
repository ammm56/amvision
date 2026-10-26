"""完整工件的动态来源回归，不把局部诊断窗口冒充已审核工件配方。"""

import numpy as np

from backend.contracts.workflows.boundary3d import ExtractBoundaryParameters
from backend.contracts.workflows.geometry3d_observations import Features3d, Pose3d
from custom_nodes._metrology3d_nodes.shared.boundary_runtime import extract_boundary
from custom_nodes._metrology3d_nodes.shared.fit_boundary import fit_boundary
from custom_nodes._metrology3d_nodes.shared.geometry_preview import attach_geometry
from custom_nodes._metrology3d_nodes.shared.measure_extents import measure_extents
from custom_nodes._metrology3d_nodes.shared.measure_hole import measure_hole
from tests.integration.metrology3d.test_boundary_extraction import extract_parameters
from tests.test_metrology3d_boundary_contracts import line_parameters, circle_parameters
from tests.test_metrology3d_dimension_contracts import extent_parameters
from tests.test_metrology3d_dimension_runtime import hole_parameters
from tests.test_metrology3d_dynamic_contour import inherited


def check_sample_contours(runtime, cloud, result, item, roi, preview, display):
    """本次位姿/测量端点独立求截面；不改变边界或拟合质量条件。"""
    datum = Features3d.model_validate(result.outputs["reference-feature"]).items[0]
    target = Features3d.model_validate(result.outputs["target-feature"]).items[0]
    pose = Pose3d.model_validate(result.outputs["current-pose"])
    records, groups = [], []
    for source in (
        dict(kind="fixed", value=0.0),
        dict(
            kind="measurement-ratio",
            item_id=item.item_id,
            reference_feature_id=datum.feature_id,
            target_feature_id=target.feature_id,
            ratio=0.5,
            order="target-above",
        ),
    ):
        parameters = extract_parameters(
            feature_id="fixed-section"
            if source["kind"] == "fixed"
            else "ratio-section",
            evaluation=dict(
                kind="pose",
                frame_id=pose.source_frame_id,
                length_unit=pose.length_unit,
                pose_id=pose.pose_id,
                target_frame_id=pose.target_frame_id,
            ),
            method=dict(
                kind="pose-contour",
                reference_feature_id=datum.feature_id,
                height=source,
                numeric_tolerance=1e-9,
            ),
            region=dict(roi_id=roi["roi_id"], rois=[roi]),
            surface=dict(
                alpha_radius=0.08,
                max_edge_length=0.15,
                max_normal_step=0.1,
                min_projected_area=1e-8,
            ),
            targets=[
                dict(
                    segment_id="diagnostic-section",
                    region=dict(roi_id=roi["roi_id"], rois=[roi]),
                    closed=False,
                    role="open",
                )
            ],
        )
        ratio = source["kind"] == "measurement-ratio"
        boundary = extract_boundary(
            runtime,
            cloud,
            parameters,
            contour_plane=datum,
            pose=pose,
            measurement=item if ratio else None,
            measurement_planes=(datum, target) if ratio else (),
            cancel=lambda: None,
        )
        feature = boundary.items[0]
        resolution = feature.method.resolution
        transform = np.asarray(pose.transform.matrix)
        origin = -transform[:3, :3].T @ transform[:3, 3]
        normal = transform[2, :3]
        if ratio and item.value <= 0:
            assert (
                feature.reason == "contour_height_order"
                and resolution.evaluation is None
            )
        else:
            height = (
                float((np.mean(item.geometry.endpoints, axis=0) - origin) @ normal)
                if ratio
                else 0.0
            )
            np.testing.assert_allclose(
                resolution.evaluation.origin, origin + height * normal, atol=1e-10
            )
            raw = parameters.model_dump(mode="json")
            raw["evaluation"] = resolution.evaluation.model_dump(mode="json")
            raw["method"] = dict(
                kind="section",
                origin=resolution.evaluation.origin,
                normal=normal,
                numeric_tolerance=1e-9,
            )
            explicit = extract_boundary(
                runtime,
                cloud,
                ExtractBoundaryParameters.model_validate(raw),
                cancel=lambda: None,
            ).items[0]
            assert explicit.valid == feature.valid and explicit.reason == feature.reason
            assert explicit.geometry == feature.geometry
        selection = dict(
            feature_id=feature.feature_id, segment_ids=["diagnostic-section"]
        )
        fitted = fit_boundary(
            runtime,
            boundary,
            line_parameters(
                feature_id=feature.feature_id + "-line",
                selection=selection,
                evaluation=inherited(),
                positive_direction=dict(kind="axis", axis="u"),
            ),
            cancel=lambda: None,
        )
        circle = fit_boundary(
            runtime,
            boundary,
            circle_parameters(
                feature_id=feature.feature_id + "-circle",
                selection=selection,
                evaluation=inherited(),
            ),
            cancel=lambda: None,
        )
        extents = measure_extents(
            runtime,
            extent_parameters(
                evaluation=inherited(),
                source=dict(kind="boundary", selection=selection),
            ),
            groups=[boundary],
            cancel=lambda: None,
        )
        hole = measure_hole(
            runtime,
            [circle],
            hole_parameters(
                feature_id=circle.items[0].feature_id,
                target_kind="open-arc",
                evaluation=inherited(),
                display_direction=dict(kind="axis", axis="u"),
            ),
            cancel=lambda: None,
        )
        if not feature.valid:
            assert not fitted.items[0].valid and not circle.items[0].valid
            assert all(
                not v.valid and v.value is None
                for g in (extents, hole)
                for v in g.items
            )
        assert feature.support.observation_id == cloud.observation_id
        if feature.valid:
            assert runtime.source_point_count(feature.support) == 14745099
        groups.extend([boundary, fitted, circle])
        records.append(
            dict(
                source=source,
                height=resolution.height,
                valid=feature.valid,
                reason=feature.reason,
                evaluation=resolution.evaluation.model_dump(mode="json")
                if resolution.evaluation
                else None,
                line_reason=fitted.items[0].reason,
                circle_reason=circle.items[0].reason,
            )
        )
    body = attach_geometry(
        runtime,
        cloud,
        display,
        dict(features=[g.model_dump(mode="json") for g in groups]),
        policy=preview,
        cancel=lambda: None,
    )
    assert body["state"] == "ready", body
    return records, body
