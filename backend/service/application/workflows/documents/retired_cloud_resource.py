"""识别需重建的历史三维格式，只读核验封装身份和内容摘要。"""

import hashlib
import json

from backend.contracts.workflows.retired_cloud_resource import RetiredCloudResource
from backend.contracts.workflows.point_cloud import canonical_cloud_json
from backend.service.application.errors import InvalidRequestError


def retired_cloud_metadata(raw):
    """未知或旧内层格式绝不交给当前解码器；二维资源保持现有路径。"""
    value = json.loads(raw)
    if not isinstance(value, dict):
        return None
    content = value.get("content")
    if not isinstance(content, dict) or content.get("kind") != "point-cloud":
        return None
    cloud = content.get("point_cloud")
    if not isinstance(cloud, dict) or not isinstance(cloud.get("format_id"), str):
        raise InvalidRequestError("点云资产缺少格式身份")
    # 方法版本属于资产内容契约；旧边界方法只能保留元数据，不能当成损坏记录隐藏。
    methods = [
        part.get("method")
        for part in (cloud.get("provenance"), cloud.get("boundary"))
        if isinstance(part, dict)
    ]
    retired_boundary = any(
        isinstance(method, dict)
        and method.get("method_id") == "extract-boundary"
        and type(method.get("method_version")) is int
        and method["method_version"] == 1
        for method in methods
    )
    if cloud["format_id"] == "amvision.point-cloud-asset.v2" and not retired_boundary:
        return None
    item = RetiredCloudResource(
        reference=value.get("reference"),
        name=value.get("name"),
        created_at=value.get("created_at"),
        stored_format_id=cloud["format_id"],
        parent_assets=cloud.get("parent_assets"),
    )
    digest = hashlib.sha256(canonical_cloud_json(content)).hexdigest()
    if item.reference.kind != "point-cloud" or digest != item.reference.sha256:
        raise InvalidRequestError("历史点云资产身份或摘要不一致")
    if any(
        r.kind != "point-cloud" or r.project_id != item.reference.project_id
        for r in item.parent_assets
    ):
        raise InvalidRequestError("历史点云父资源身份不一致")
    return item
