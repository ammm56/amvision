"""完整代表配方经正式发布和独立 Runtime 验收，合法无效尺寸不得变成运行失败。"""

from tests.integration.metrology3d.representative_workflow import (
    representative_documents,
    representative_policy,
    check_representative_body,
)
from tests.integration.metrology3d.test_published_runtime import (
    published_full_sample_lifecycle,
)
from tests.point_cloud_support import spatial


def test_representative_published_full_sample_lifecycle(tmp_path, request):
    """Windows .NET / Ubuntu 协议客户端复用正式停止、切版、异常退出和回收流程。"""

    def prepare(cloud, path):
        return cloud.model_copy(
            update={"spatial": spatial()}
        ), representative_documents()

    published_full_sample_lifecycle(
        tmp_path,
        request,
        prepare=prepare,
        check_body=check_representative_body,
        point_cloud_policy=representative_policy(),
        report_name="r5-representative",
    )
