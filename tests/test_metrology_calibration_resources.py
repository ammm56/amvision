"""使用准备好的棋盘图片验证现有相机标定和新增平面标定节点。"""

from pathlib import Path

import cv2
import numpy as np
import pytest

from backend.nodes import ExecutionImageRegistry
from backend.nodes.runtime_support import register_image_matrix
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)
from custom_nodes.opencv_nodes.categories.calibration.backend.nodes.camera_calibrate import (
    handle_node as camera_calibrate,
)
from custom_nodes.opencv_nodes.categories.calibration.backend.nodes.planar_calibrate import (
    handle_node as planar_calibrate,
)

ROOT = (
    Path(__file__).resolve().parents[1]
    / "data/development/connector-inspection/synthetic-v1/calibration"
)


def request(registry, parameters, inputs=None):
    """构造已有执行框架的请求，无网络、数据集或生产文件写入。"""
    return WorkflowNodeExecutionRequest(
        node_id="calibration-check",
        node_definition=object(),
        parameters=parameters,
        input_values=inputs or {},
        execution_metadata={"execution_image_registry": registry},
    )


def test_camera_and_plane_from_actual_chessboard_images():
    """12 张渲染棋盘进入真实 Camera Calibrate；平面点分开拟合和验证。"""
    paths = sorted(ROOT.glob("*.png"))
    if not paths:
        pytest.skip("标定开发资源尚未生成")
    assert len(paths) == 12
    registry = ExecutionImageRegistry()
    images = [cv2.imdecode(np.fromfile(p, np.uint8), cv2.IMREAD_COLOR) for p in paths]
    payloads = [
        register_image_matrix(request(registry, {}), image_matrix=image)
        for image in images
    ]
    result = camera_calibrate(
        request(
            registry,
            dict(columns=9, rows=6, square_size=2.0, min_views=12),
            {"images": {"items": payloads}},
        )
    )["camera_calibration"]
    assert result["observation_count"] == 12
    assert result["rms_reprojection_error"] < 0.2
    assert abs(result["camera_matrix"][0][0] / 1777.7777777777778 - 1) < 0.01
    found, corners = cv2.findChessboardCornersSB(
        cv2.cvtColor(images[0], cv2.COLOR_BGR2GRAY), (9, 6)
    )
    assert found
    object_points = np.mgrid[0:9, 0:6].T.reshape(-1, 2).astype(float) * 2.0
    # 内部验证点不参与求解；外部四角始终保留在拟合覆盖区。
    holdout = {12, 22, 31, 41}
    points = [
        dict(image=p.tolist(), world=w.tolist())
        for p, w in zip(corners.reshape(-1, 2), object_points)
    ]
    params = dict(
        image_width=1280,
        image_height=800,
        model="homography",
        unit="millimeter",
        plane_id="synthetic-checkerboard",
        control_points=[p for i, p in enumerate(points) if i not in holdout],
        validation_points=[p for i, p in enumerate(points) if i in holdout],
        max_validation_error=0.02,
    )
    output = planar_calibrate(request(registry, params))
    assert output["calibration"]["validation_max_error"] < 0.02
    # 显式改变独立参考量值必须失败，不能由拟合自动吸收。
    wrong = [
        dict(image=p["image"], world=[p["world"][0] + 1, p["world"][1]])
        for p in params["validation_points"]
    ]
    with pytest.raises(InvalidRequestError, match="误差"):
        planar_calibrate(request(registry, params | {"validation_points": wrong}))
