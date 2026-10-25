"""严格解码失败时提供有界资源错误元数据，不读取旧格式点数据。"""

import hashlib
import json

from pydantic import ValidationError
from backend.contracts.workflows.cloud_resource_errors import UnavailableCloudResource
from backend.contracts.workflows.measurement_resources import (
    MeasurementResourceDocument,
)
from backend.contracts.workflows.point_cloud import canonical_cloud_json
from backend.service.application.errors import InvalidRequestError


def unavailable_cloud_metadata(raw):
    """仅接受当前 schema；失败项不能选用，正常项继续原读取与摘要校验。"""
    value = json.loads(raw)
    if not isinstance(value, dict):
        return None
    content = value.get("content")
    if not isinstance(content, dict) or content.get("kind") != "point-cloud":
        return None
    cloud = content.get("point_cloud")
    if not isinstance(cloud, dict) or not isinstance(cloud.get("format_id"), str):
        raise InvalidRequestError("点云资产缺少格式身份")
    try:
        MeasurementResourceDocument.model_validate(value)
    except ValidationError:
        pass
    else:
        return None
    item = UnavailableCloudResource(
        reference=value.get("reference"),
        name=value.get("name"),
        created_at=value.get("created_at"),
        stored_format_id=cloud["format_id"],
        parent_assets=cloud.get("parent_assets"),
    )
    digest = hashlib.sha256(canonical_cloud_json(content)).hexdigest()
    if item.reference.kind != "point-cloud" or digest != item.reference.sha256:
        raise InvalidRequestError("不可用点云资产身份或摘要不一致")
    if any(
        r.kind != "point-cloud" or r.project_id != item.reference.project_id
        for r in item.parent_assets
    ):
        raise InvalidRequestError("不可用点云父资源身份不一致")
    return item
