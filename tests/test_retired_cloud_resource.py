"""旧三维内容仅管理可见，不允许执行或静默迁移。"""

import json
from hashlib import sha256
import pytest
from backend.contracts.workflows.point_cloud import canonical_cloud_json
from backend.service.application.errors import InvalidRequestError, ResourceInUseError
from tests.test_point_cloud_assets import save
from tests.point_cloud_support import create_resource_service


@pytest.mark.parametrize("retired", ["format", "provenance", "boundary"])
def test_old_asset_is_listed_readonly_but_rejected_for_use(tmp_path, retired):
    """仅改测试数据，生产旧文件保持不动。"""
    service = create_resource_service(tmp_path)
    document = save(service)
    raw = document.model_dump(mode="json")
    cloud = raw["content"]["point_cloud"]
    if retired == "format":
        cloud["format_id"] = "amvision.point-cloud-asset.v1"
    else:
        # 旧方法仅核验封装摘要；这里不以旧结构执行算法或读取 blob。
        cloud[retired] = {
            "method": {"method_id": "extract-boundary", "method_version": 1}
        }
    raw["reference"]["sha256"] = sha256(
        canonical_cloud_json(raw["content"])
    ).hexdigest()
    path = service.storage.resolve(service.version_key(document.reference))
    path.write_text(json.dumps(raw), encoding="utf-8")
    before = path.read_bytes()
    rows = service.list_versions(project_id="test", include_retired=True)
    assert rows[0].state == "rebuild-required" and rows[0].content is None
    with pytest.raises(InvalidRequestError, match="旧资产"):
        service.read(rows[0].reference, project_id="test")
    with pytest.raises(InvalidRequestError, match="旧资产"):
        service.get_version(
            project_id="test", resource_id=rows[0].reference.resource_id, version=1
        )
    assert path.read_bytes() == before


def test_retired_asset_still_protects_its_parent(tmp_path):
    """历史元数据只用于引用保护，禁止借停用状态删除其来源。"""
    service = create_resource_service(tmp_path)
    parent = save(service)
    child = save(service, identity="b" * 64)
    raw = child.model_dump(mode="json")
    raw["content"]["point_cloud"]["format_id"] = "amvision.point-cloud-asset.v1"
    raw["content"]["point_cloud"]["parent_assets"] = [
        parent.reference.model_dump(mode="json")
    ]
    raw["reference"]["sha256"] = sha256(
        canonical_cloud_json(raw["content"])
    ).hexdigest()
    path = service.storage.resolve(service.version_key(child.reference))
    path.write_text(json.dumps(raw), encoding="utf-8")
    before = path.read_bytes()
    with pytest.raises(ResourceInUseError, match="点云资产引用"):
        service.delete(parent.reference, project_id="test")
    assert service.read(parent.reference, project_id="test") == parent
    assert path.read_bytes() == before
    unrelated = save(service, identity="c" * 64)
    service.delete(unrelated.reference, project_id="test")
    assert path.read_bytes() == before
