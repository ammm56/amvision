"""台面配准公开节点配置；复用已核对的工件 ROI/质量，不更改工件配方。"""

import numpy as np

from backend.contracts.workflows.geometry3d import CropCloudParameters
from tests.integration.metrology3d.representative_recipe import supports, plane, frame
from tests.test_metrology3d_plane import plane_parameters
from tests.test_metrology3d_frame import frame_parameters


def datum_configs(rotation, translation, *, full_sample=False):
    """参考云的已知变换同时作用于显式 ROI 和基准方向；算法仍实际拟合。"""
    if full_sample:
        crop, fit, build = supports()["D"], plane("D"), frame()
    else:
        crop = CropCloudParameters(
            roi_id="table",
            rois=[
                dict(
                    roi_id="table",
                    kind="box",
                    frame_id="fixture",
                    length_unit="mm",
                    geometry=dict(
                        center=[0, 0, 0],
                        size=[40, 40, 0.01],
                        rotation=np.eye(3).tolist(),
                    ),
                )
            ],
        )
        fit = plane_parameters(feature_id="primary")
        build = frame_parameters(
            origin=dict(kind="anchor-projection", anchor=[0, 0, 0])
        )
    result = []
    for label, r, t in (
        ("fixture", np.eye(3), np.zeros(3)),
        ("reference", rotation, translation),
    ):
        c, p, f = (v.model_dump(mode="json") for v in (crop, fit, build))
        for roi in c["rois"]:
            roi["frame_id"] = label
            if roi["kind"] == "box":
                g = roi["geometry"]
                g["center"] = (r @ g["center"] + t).tolist()
                g["rotation"] = (r @ g["rotation"]).tolist()
        p["positive_normal"] = (r @ p["positive_normal"]).tolist()
        f.update(pose_id=f"{label}-datum", target_frame_id=f"{label}-datum")
        f["positive_z"] = (r @ f["positive_z"]).tolist()
        f["x_axis"]["direction"] = (r @ f["x_axis"]["direction"]).tolist()
        f["origin"]["anchor"] = (r @ f["origin"]["anchor"] + t).tolist()
        result.append(
            (
                type(crop).model_validate(c),
                type(fit).model_validate(p),
                type(build).model_validate(f),
            )
        )
    return tuple(result)
