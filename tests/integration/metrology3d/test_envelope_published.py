"""F3 正式目录、发布版本、Trigger 和完整工件结果的跨进程验收。"""

from pathlib import Path

from tests.integration.metrology3d.workpiece_workflow import (
    workpiece_documents,
    check_workpiece_body,
)
from tests.integration.metrology3d.representative_workflow import representative_policy
from tests.integration.metrology3d.test_published_runtime import (
    published_full_sample_lifecycle,
)
from tests.point_cloud_support import spatial


def test_envelope_published_full_sample_lifecycle(tmp_path, request):
    """沿现有真实准入和生命周期测试，不注入 handler 或测试 manifest。"""

    def prepare(cloud, path):
        return cloud.model_copy(update={"spatial": spatial()}), workpiece_documents(
            visible=True
        )

    def check(body):
        check_workpiece_body(
            body,
            matrix=Path(__file__).parents[3]
            / "docs/development/assets/r5-f3/workpiece-matrix.json",
        )

    published_full_sample_lifecycle(
        tmp_path,
        request,
        prepare=prepare,
        check_body=check,
        point_cloud_policy=representative_policy(),
        report_name="r5-f3-",
    )
