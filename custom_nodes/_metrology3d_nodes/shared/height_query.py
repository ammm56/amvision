"""有限目标区局部拟面与基准方向高度，复用 M2 的裁剪及拟合。"""

import numpy as np

from backend.contracts.workflows.geometry3d import CropCloudParameters
from backend.service.application.runtime.exception_cleanup import (
    release_exception_frames,
)
from custom_nodes._metrology3d_nodes.shared.crop_roi import crop_roi
from custom_nodes._metrology3d_nodes.shared.fit_plane import fit_plane
from custom_nodes._metrology3d_nodes.shared.measurement_result import (
    directional_measurement,
)
from custom_nodes._metrology3d_nodes.shared.measurement_support import (
    require_cloud,
    select_planes,
)
from custom_nodes._metrology3d_nodes.shared.measurement_query import resolve_query


def height_query(runtime, cloud, groups, parameters, *, pose=None, cancel):
    """高度为同线目标交点减基准交点；返回局部面供现有显示复用。"""
    try:
        cancel()
        require_cloud(runtime, cloud, parameters, cloud.observation_id)
        reference = select_planes(
            runtime,
            groups,
            parameters,
            [parameters.reference_feature_id],
            observation_id=cloud.observation_id,
        )[0]
        resolution = resolve_query(
            runtime, parameters, parameters, pose, cloud.observation_id, cancel=cancel
        )
        if resolution.line is None:
            target = fit_plane(
                runtime,
                cloud.unavailable("query_pose_unavailable"),
                parameters.plane_fit,
                cancel=cancel,
            )
            return directional_measurement(
                runtime,
                [reference, target.items[0]],
                parameters,
                resolution,
                cancel=cancel,
            ), target
        line = resolution.line
        low, high = parameters.search_interval
        with np.errstate(over="raise", invalid="raise"):
            center = np.asarray(line.query_position) + (
                low / 2 + high / 2
            ) * np.asarray(line.direction)
        roi = CropCloudParameters(
            roi_id=parameters.item_id,
            rois=[
                dict(
                    roi_id=parameters.item_id,
                    kind="cylinder",
                    frame_id=parameters.frame_id,
                    length_unit=parameters.length_unit,
                    geometry=dict(
                        center=center,
                        axis=line.direction,
                        radius=parameters.search_radius,
                        length=high - low,
                    ),
                )
            ],
        )
        local, _ = crop_roi(runtime, cloud, roi, cancel=cancel)
        target = fit_plane(runtime, local, parameters.plane_fit, cancel=cancel)
        evidence = directional_measurement(
            runtime, [reference, target.items[0]], parameters, resolution, cancel=cancel
        )
        cancel()
        return evidence, target
    except BaseException as error:
        release_exception_frames(error)
        raise
