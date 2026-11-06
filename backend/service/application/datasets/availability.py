"""版本基础资源可用性；实时检查，不把数据库登记等同于磁盘可用。"""

from datetime import datetime, timezone
import os
from typing import Literal

from backend.service.application.datasets.content import content_access, content_key
from backend.service.application.errors import InvalidRequestError, ResourceConflictError
from backend.service.infrastructure.filesystem.shared_files import open_shared_read

VersionState = Literal["", "available", "missing", "unavailable", "updating", "empty"]


def check_version_resources(storage, version: dict) -> dict:
    """检查当前内容目录与必需清单可读；不扫描全量图片或进行内容校验。"""
    state, reason = "available", "resources_readable"
    try:
        with content_access(storage, version["dataset_version_id"]):
            root = storage.resolve(content_key(
                version["project_id"], version["dataset_id"],
                version["dataset_version_id"], version.get("metadata"),
            )).resolve()
            if not root.is_relative_to(storage.root_dir.resolve()):
                raise InvalidRequestError("版本资源路径无效")
            # 打开目录能区分不存在与访问被拒绝；不用 exists() 隐藏权限错误。
            for name in ("", "images", "samples", "indexes"):
                path = (root / name).resolve()
                if not path.is_relative_to(root):
                    raise InvalidRequestError("版本资源路径无效")
                with os.scandir(path) as entries:
                    next(entries, None)
            for name in ("dataset-version.json", "categories.json"):
                path = (root / "manifests" / name).resolve()
                if not path.is_relative_to(root):
                    raise InvalidRequestError("版本资源路径无效")
                with open_shared_read(path) as stream:
                    if not stream.read(1):
                        return _result("unavailable", "empty_manifest")
            if not version.get("has_samples", version.get("sample_count", 0) > 0):
                state, reason = "empty", "no_samples"
    except ResourceConflictError:
        state, reason = "updating", "content_busy"
    except (FileNotFoundError, NotADirectoryError):
        state, reason = "missing", "resources_missing"
    except PermissionError:
        state, reason = "unavailable", "access_denied"
    except InvalidRequestError:
        state, reason = "unavailable", "invalid_path"
    except OSError:
        state, reason = "unavailable", "storage_error"
    return _result(state, reason)


def _result(state: str, reason: str) -> dict:
    """返回稳定原因码与检查时间，不暴露服务器绝对路径。"""
    return {"state": state, "reason": reason,
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "scope": "version_resources"}


def list_version_availability(repository, storage, project_id: str, *, state: VersionState = "",
                              offset: int = 0, limit: int = 20, **filters) -> dict:
    """无筛选仅检查当前页；状态筛选先检查轻量身份，再聚合匹配页计数。"""
    if not state:
        page = repository.versions(project_id, offset=offset, limit=limit, **filters)
        for item in page["items"]:
            item["availability"] = check_version_resources(storage, item)
        return page
    matched, total = {}, 0
    for candidate in repository.version_candidates(project_id, **filters):
        availability = check_version_resources(storage, candidate)
        if availability["state"] != state:
            continue
        if offset <= total < offset + limit:
            matched[candidate["dataset_version_id"]] = availability
        total += 1
    items = repository.version_summaries(list(matched))
    for item in items:
        item["availability"] = matched[item["dataset_version_id"]]
    return {"items": items, "total": total, "offset": offset, "limit": limit}
