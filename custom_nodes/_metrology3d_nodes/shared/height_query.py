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


def height_query(runtime, cloud, groups, parameters, *, cancel):
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
        low, high = parameters.search_interval
        with np.errstate(over="raise", invalid="raise"):
            center = np.asarray(parameters.query_position) + (
                low / 2 + high / 2
            ) * np.asarray(parameters.direction)
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
                        axis=parameters.direction,
                        radius=parameters.search_radius,
                        length=high - low,
                    ),
                )
            ],
        )
        local, _ = crop_roi(runtime, cloud, roi, cancel=cancel)
        target = fit_plane(runtime, local, parameters.plane_fit, cancel=cancel)
        evidence = directional_measurement(
            runtime, [reference, target.items[0]], parameters, cancel=cancel
        )
        cancel()
        return evidence, target
    except BaseException as error:
        release_exception_frames(error)
        raise
