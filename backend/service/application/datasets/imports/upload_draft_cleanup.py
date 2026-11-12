"""草稿过期回收；复用既有维护入口和文件句柄锁，不另建后台调度器。"""

from collections import defaultdict
import re
from time import time

from backend.service.application.datasets.content import content_access
from backend.service.application.errors import ResourceConflictError


def prune_owner(storage, prefix: str, *, cutoff: float) -> list[str]:
    """排他核对一个所有者；同一草稿及其元数据全部过期才删除，活动操作跳过。"""
    root = storage.resolve_deletion_path(prefix)
    if not root.is_dir():
        return []
    removed = []
    try:
        with content_access(storage, f"upload-drafts:{prefix}", write=True):
            groups = defaultdict(list)
            try:
                paths = list(root.iterdir())
            except FileNotFoundError:
                return []
            for path in paths:
                # write_json 原子写入时可能遗留同目录临时文件。
                match = re.fullmatch(
                    r"([a-f0-9]{32})(?:\.json|\.submitting)?", path.name
                )
                temporary = re.fullmatch(
                    r"\.([a-f0-9]{32})\.json\.[a-f0-9]{12}\.tmp", path.name
                )
                if (match or temporary) and not path.is_symlink() and path.is_file():
                    groups[(match or temporary)[1]].append(path)
            for paths in groups.values():
                try:
                    if max(path.stat().st_mtime for path in paths) >= cutoff:
                        continue
                    for path in paths:
                        key = path.relative_to(storage.root_dir).as_posix()
                        storage.resolve_deletion_path(key).unlink(missing_ok=True)
                        removed.append(key)
                except (FileNotFoundError, PermissionError):
                    continue
    except ResourceConflictError:
        pass
    return removed


def cleanup_upload_drafts(storage, *, now: float | None = None) -> list[str]:
    """扫描所有项目/主体，独立于原用户再次登录；旧目录仅回收，不提供读取兼容。"""
    from .upload_draft import DatasetUploadDrafts

    cutoff = (time() if now is None else now) - DatasetUploadDrafts.ttl_seconds
    parents = []
    projects = storage.resolve_deletion_path("projects")
    if projects.is_dir():
        parents.extend(
            p / "dataset-upload-drafts"
            for p in projects.iterdir()
            if p.is_dir() and not p.is_symlink()
        )
    # 升级前草稿无法可靠关联项目；过期后清理，客户端须重新上传。
    parents.append(storage.resolve_deletion_path("dataset-upload-drafts"))
    removed = []
    for parent in parents:
        if not parent.is_dir() or parent.is_symlink():
            continue
        try:
            owners = list(parent.iterdir())
        except FileNotFoundError:
            continue
        for owner in owners:
            if (
                not re.fullmatch(r"[a-f0-9]{64}", owner.name)
                or not owner.is_dir()
                or owner.is_symlink()
            ):
                continue
            removed.extend(
                prune_owner(
                    storage,
                    owner.relative_to(storage.root_dir).as_posix(),
                    cutoff=cutoff,
                )
            )
    return sorted(removed)
