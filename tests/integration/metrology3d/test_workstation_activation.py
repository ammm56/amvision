"""本机批准的显式配置，复用真实发布、Trigger 和客户端生命周期验收。"""

import json
from pathlib import Path

from backend.service.application.workflows.point_cloud.execution_policy import (
    PointCloudExecutionPolicy,
)
from tests.integration.metrology3d.test_published_runtime import (
    published_full_sample_lifecycle,
)


def test_workstation_full_sample_and_stop(tmp_path, request):
    """普通节点包准入，运行中停止/切版拒绝、断开回收和恢复均走正式入口。"""
    root = Path(__file__).resolve().parents[3]
    config = json.loads(
        (root / "custom_nodes/metrology3d_nodes/workstation.example.json").read_text(
            "utf-8"
        )
    )
    policy = PointCloudExecutionPolicy.model_validate(
        config["workflow_runtime"]["point_cloud"]
    )
    published_full_sample_lifecycle(
        tmp_path,
        request,
        point_cloud_policy=policy,
        report_name="formal-workstation-",
    )
