"""工作区操作提交与后台执行；复用 Task、Outbox、执行凭证和受管版本目录。"""

from contextlib import contextmanager, ExitStack
from dataclasses import replace
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5
from backend.service.application.datasets.content import (
    content_access,
    content_key,
    require_revision,
    obsolete_content,
    cleanup_content,
)

from backend.contracts.datasets.workspace_jobs import DatasetWorkspaceJobRequest
from backend.service.application.datasets.imports.formats.sample_media import copy_assets
from backend.service.application.datasets.workspace_analysis import (
    compare_versions,
    derivation_plan,
    image_path,
    quality_report,
    stable_sample_id,
)
from backend.service.application.datasets.annotation_handoff import check_return
from backend.service.application.errors import (
    InvalidRequestError,
    ResourceConflictError,
    ResourceNotFoundError,
    ServiceError,
)
from backend.service.application.tasks.task_service import (
    CreateTaskRequest,
    SqlAlchemyTaskService,
    TaskQueueSubmission,
    TaskStateCommandRequest,
)
from backend.service.domain.datasets.dataset_version import serialize_dataset_annotation
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork

WORKSPACE_TASK_KIND = "dataset-workspace"
WORKSPACE_QUEUE = "dataset-workspace"


class DatasetWorkspaceJobs:
    """固定版本的只读检查和显式衍生服务。"""

    def __init__(self, factory, storage):
        """绑定本地存储及已有任务服务。"""
        self.factory = factory
        self.storage = storage
        self.tasks = SqlAlchemyTaskService(factory)

    @contextmanager
    def unit(self):
        """每次数据库访问及时释放连接，不跨磁盘扫描持有事务。"""
        unit = SqlAlchemyUnitOfWork(self.factory.create_session())
        try:
            yield unit
        finally:
            unit.close()

    @staticmethod
    def task_id(project_id, dataset_id, version_id, request_id):
        """请求身份只在所属版本内有效，不能碰撞其他项目。"""
        return (
            "task-"
            + uuid5(
                NAMESPACE_URL,
                f"dataset:{project_id}:{dataset_id}:{version_id}:{request_id}",
            ).hex
        )

    @staticmethod
    def signature(spec):
        """预检查和正式创建必须使用同一源版本与配置。"""
        return sha256(
            json.dumps(
                {
                    k: spec[k]
                    for k in (
                        "project_id",
                        "dataset_id",
                        "dataset_version_id",
                        "config",
                        "expected_content_revision",
                    )
                },
                ensure_ascii=False,
                sort_keys=True,
            ).encode()
        ).hexdigest()

    def submit(self, identity, body: DatasetWorkspaceJobRequest, created_by):
        """提交轻量规格；大图读取和完整版本加载仅发生在 worker。"""
        spec = {
            **body.model_dump(mode="json"),
            **{
                key: identity[key]
                for key in ("project_id", "dataset_id", "dataset_version_id")
            },
        }
        task_id = self.task_id(
            identity["project_id"],
            identity["dataset_id"],
            identity["dataset_version_id"],
            body.request_id,
        )
        with self.unit() as unit:
            existing = unit.tasks.get_task(task_id)
            if existing:
                if any(
                    existing.task_spec.get(k) != v
                    for k, v in spec.items()
                    if k != "expected_content_revision"
                ) or (
                    body.expected_content_revision is not None
                    and existing.task_spec.get("expected_content_revision")
                    != body.expected_content_revision
                ):
                    raise ResourceConflictError("该请求身份已经用于其他配置")
                return existing
            current_revision = identity.get("metadata", {}).get("content_revision", "")
            expected = body.expected_content_revision
            if expected is None:
                expected = current_revision
            if current_revision != expected:
                raise ResourceConflictError("当前版本的样本已变化，请刷新后重新操作")
            spec["expected_content_revision"] = expected
            if body.compare_version_id:
                other = unit.dataset_catalog.version_identity(
                    identity["dataset_id"], body.compare_version_id
                )
                if other["project_id"] != identity["project_id"]:
                    raise ResourceNotFoundError("找不到比较版本")
            if body.config.selection:
                selected = unit.dataset_catalog.selection_summary(
                    identity["dataset_version_id"], body.config.selection.model_dump()
                )
                if not selected["sample_count"]:
                    raise InvalidRequestError("当前选择没有样本")
            if body.config.exclude_selection:
                removed = unit.dataset_catalog.selection_summary(
                    identity["dataset_version_id"],
                    body.config.exclude_selection.model_dump(),
                )
                if removed["sample_count"] == 0:
                    raise InvalidRequestError("没有选择待删除样本")
            if body.operation.startswith("return-"):
                returned = unit.dataset_catalog.version_identity(
                    identity["dataset_id"], body.config.returned_version_id
                )
                export = unit.dataset_exports.get_dataset_export(
                    body.config.handoff_export_id
                )
                if (
                    returned["project_id"] != identity["project_id"]
                    or export is None
                    or export.project_id != identity["project_id"]
                    or export.dataset_version_id != identity["dataset_version_id"]
                    or export.status != "completed"
                    or not export.metadata.get("annotation_handoff")
                    or export.metadata.get("files_cleaned_at")
                ):
                    raise InvalidRequestError(
                        "回传版本或交接导出不属于当前来源，或交接文件已清理"
                    )
            if body.operation in {"derive", "return-apply"}:
                checked = unit.tasks.get_task(body.checked_task_id)
                required_check = (
                    "derive-check" if body.operation == "derive" else "return-check"
                )
                if (
                    checked is None
                    or checked.task_kind != WORKSPACE_TASK_KIND
                    or checked.state != "succeeded"
                    or checked.task_spec.get("operation") != required_check
                    or checked.result.get("signature") != self.signature(spec)
                    or checked.result.get("can_create") is False
                ):
                    raise InvalidRequestError("配置与已完成检查不一致，请重新检查")
        return self.create_or_retrieve(
            CreateTaskRequest(
                project_id=identity["project_id"],
                task_kind=WORKSPACE_TASK_KIND,
                task_id=task_id,
                display_name={
                    "quality": "数据集质量检查",
                    "derive-check": "检查新版本",
                    "derive": "创建数据集版本",
                    "revise": "更新数据集样本",
                    "compare": "比较数据集版本",
                    "return-check": "检查外部标注回传",
                    "return-apply": "创建回传版本",
                }[body.operation],
                created_by=created_by,
                task_spec=spec,
                queue_submission=TaskQueueSubmission(queue_name=WORKSPACE_QUEUE),
            )
        )

    def create_or_retrieve(self, request: CreateTaskRequest):
        """并发同请求发生唯一键冲突时返回已提交任务，不重复入队。"""
        try:
            return self.tasks.create_task(request)
        except ServiceError:
            with self.unit() as unit:
                existing = unit.tasks.get_task(request.task_id)
            if existing is None:
                raise
            if existing.task_spec != request.task_spec:
                raise ResourceConflictError("该请求身份已经用于其他配置")
            return existing

    def run(self, task_id, fence, tick):
        """共享读取准备文件，提交时切换为排他访问。"""
        task = self.tasks.get_task(task_id).task
        with ExitStack() as reads:
            for version_id in sorted(
                set(
                    filter(
                        None,
                        [
                            task.task_spec["dataset_version_id"],
                            task.task_spec.get("compare_version_id"),
                            task.task_spec.get("config", {}).get("returned_version_id"),
                        ],
                    )
                )
            ):
                reads.enter_context(content_access(self.storage, version_id))
            return self._run(task_id, fence, tick, reads)

    def _run(self, task_id, fence, tick, reads):
        """先完成磁盘产物，再在同一 CAS 事务登记版本与成功状态。"""
        task = self.tasks.get_task(task_id).task
        self.tasks.validate_task_execution_fence(task_id=task_id, fence=fence)
        request = DatasetWorkspaceJobRequest.model_validate(
            {
                k: v
                for k, v in task.task_spec.items()
                if k not in {"project_id", "dataset_id", "dataset_version_id"}
            }
        )
        version_id = task.task_spec["dataset_version_id"]
        with self.unit() as unit:
            source = unit.datasets.get_dataset_version(version_id)
            if (
                source is None
                or source.project_id != task.project_id
                or source.dataset_id != task.task_spec["dataset_id"]
            ):
                raise ResourceNotFoundError("来源版本已不可用")
            require_revision(source, request.expected_content_revision)
            selected_ids = (
                unit.dataset_catalog.selected_ids(
                    version_id, request.config.selection.model_dump()
                )
                if request.config.selection
                else None
            )
            if request.config.exclude_selection:
                excluded = unit.dataset_catalog.selected_ids(
                    version_id, request.config.exclude_selection.model_dump()
                )
                selected_ids = {s.sample_id for s in source.samples} - excluded
            other = (
                unit.datasets.get_dataset_version(request.compare_version_id)
                if request.operation == "compare"
                else None
            )
            returned = (
                unit.datasets.get_dataset_version(request.config.returned_version_id)
                if request.operation.startswith("return-")
                else None
            )
            export = (
                unit.dataset_exports.get_dataset_export(
                    request.config.handoff_export_id
                )
                if request.operation.startswith("return-")
                else None
            )
        tick()
        derived = None
        output_prefix = None
        result = {
            "operation": request.operation,
            "dataset_version_id": version_id,
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            if request.operation == "quality":
                result.update(quality_report(self.storage, source, tick))
            elif request.operation == "compare":
                if (
                    other is None
                    or other.project_id != source.project_id
                    or other.dataset_id != source.dataset_id
                ):
                    raise ResourceNotFoundError("比较版本已不可用")
                result.update(compare_versions(self.storage, source, other, tick))
                result["compare_version_id"] = other.dataset_version_id
            else:
                image_sources = None
                if request.operation.startswith("return-"):
                    if (
                        returned is None
                        or returned.project_id != source.project_id
                        or returned.dataset_id != source.dataset_id
                        or export is None
                        or export.dataset_version_id != version_id
                        or export.metadata.get("files_cleaned_at")
                    ):
                        raise InvalidRequestError("交接资源已变化，请重新选择")
                    planned, summary, image_sources = check_return(
                        self.storage, source, returned, export, request.config, tick
                    )
                    result["returned_version_id"] = returned.dataset_version_id
                else:
                    planned, summary = derivation_plan(
                        source, request.config, selected_ids
                    )
                result.update(summary)
                result["signature"] = self.signature(task.task_spec)
                if request.operation in {"derive", "revise", "return-apply"}:
                    if summary.get("can_create") is False:
                        raise InvalidRequestError("回传检查仍有阻止项，未创建版本")
                    updating = request.operation == "revise"
                    new_id = (
                        version_id
                        if updating
                        else "dataset-version-" + uuid5(NAMESPACE_URL, task_id).hex[:12]
                    )
                    revision = uuid5(NAMESPACE_URL, task_id).hex if updating else ""
                    output_prefix = content_key(
                        source.project_id,
                        source.dataset_id,
                        new_id,
                        {"content_revision": revision},
                    )
                    with self.unit() as unit:
                        if (
                            not updating
                            and unit.datasets.get_dataset_version(new_id) is not None
                        ):
                            raise ResourceConflictError("目标版本已经存在")
                    derived = self.write_version(
                        source,
                        planned,
                        new_id,
                        request,
                        task_id,
                        tick,
                        image_sources=image_sources,
                        content_revision=revision,
                    )
                    result[
                        "updated_version_id" if updating else "created_version_id"
                    ] = new_id
            tick()

            def persist(unit):
                """与任务成功状态原子提交，取消抢先成功时不会留下可见版本。"""
                if request.operation == "revise":
                    require_revision(
                        unit.datasets.get_dataset_version(version_id),
                        request.expected_content_revision,
                    )
                unit.datasets.save_dataset_version(derived)

            reads.close()
            with content_access(self.storage, version_id, write=True):
                self.tasks.execute_task_state_command(
                    TaskStateCommandRequest(
                        task_id=task_id,
                        target_state="succeeded",
                        expected_states=("running",),
                        expected_current_attempt_no=task.current_attempt_no,
                        fence=fence,
                        result_patch=result,
                        progress_patch={"percent": 100, "stage": "completed"},
                        message="数据集操作完成",
                    ),
                    persist_result=persist if derived else None,
                )
                if derived and request.operation == "revise":
                    cleanup_content(self.storage, derived)
            return result
        except Exception:
            # 提交结果不明确时只查询，不猜测；已登记的版本绝不能删除。
            if output_prefix:
                with self.unit() as unit:
                    registered = unit.datasets.get_dataset_version(
                        derived.dataset_version_id if derived else version_id
                    )
                if (
                    registered is None
                    or content_key(
                        registered.project_id,
                        registered.dataset_id,
                        registered.dataset_version_id,
                        registered.metadata,
                    )
                    != output_prefix
                ):
                    self.storage.delete_tree(output_prefix)
            raise

    def write_version(
        self,
        source,
        planned,
        version_id,
        request,
        task_id,
        tick,
        *,
        image_sources=None,
        content_revision="",
    ):
        """按归一化布局复制素材；源图片、标注和引用均不修改。"""
        layout = self.storage.prepare_version_layout(
            project_id=source.project_id,
            dataset_id=source.dataset_id,
            dataset_version_id=version_id,
            content_revision=content_revision,
        )
        samples = []
        indexes = {split: [] for split in ("train", "val", "test")}
        originals = {s.sample_id: s for s in source.samples}
        for index, sample in enumerate(planned.samples):
            tick(index, len(planned.samples))
            sample_id = (
                sample.sample_id
                if content_revision
                else f"sample-{version_id}-{index + 1}"
            )
            image_name = "preview.png" if source.task_type == "point-cloud" else Path(sample.file_name).name
            image_key = f"images/{sample.split}/{sample_id}/{image_name}"
            target = self.storage.resolve(f"{layout.version_path}/{image_key}")
            target.parent.mkdir(parents=True, exist_ok=True)
            source_path = (image_sources or {}).get(sample.sample_id) or image_path(
                self.storage, source, originals[sample.sample_id]
            )
            with source_path.open("rb") as reader, target.open("wb") as writer:
                while block := reader.read(1024 * 1024):
                    writer.write(block)
                    tick()
            copy_assets(self.storage, sample.metadata, source_path, f"{layout.version_path}/{image_key}")
            copied = replace(
                sample,
                sample_id=sample_id,
                annotations=sample.annotations
                if content_revision
                else tuple(
                    replace(a, annotation_id=f"ann-{version_id}-{index + 1}-{i + 1}")
                    for i, a in enumerate(sample.annotations)
                ),
                metadata={
                    **sample.metadata,
                    "origin_sample_id": stable_sample_id(sample),
                    "source_sample_id": sample.sample_id,
                    "image_object_key": image_key,
                },
            )
            samples.append(copied)
            sample_key = f"{layout.samples_dir}/{sample.split}/{sample_id}.json"
            self.storage.write_json(
                sample_key,
                {
                    "sample_id": sample_id,
                    "image_id": sample.image_id,
                    "file_name": sample.file_name,
                    "split": sample.split,
                    "width": sample.width,
                    "height": sample.height,
                    "image_object_key": image_key,
                    "annotations": [
                        serialize_dataset_annotation(a) for a in copied.annotations
                    ],
                    "metadata": copied.metadata,
                },
            )
            indexes[sample.split].append(
                {
                    "sample_id": sample_id,
                    "image_id": sample.image_id,
                    "file_name": sample.file_name,
                    "image_object_key": image_key,
                    "sample_object_key": sample_key,
                    "annotation_count": len(sample.annotations),
                }
            )
        metadata = {
            key: value
            for key, value in source.metadata.items()
            if key
            in {
                "pose_category_schemas",
                "keypoint_flip_indices",
                "reference_values",
                "calibration",
            }
        }
        metadata.update(
            {
                "created_at": datetime.now(timezone.utc).isoformat(),
                "source_kind": "annotation-return"
                if request.operation == "return-apply"
                else "derived",
                "parent_version_id": source.dataset_version_id,
                "creation_task_id": task_id,
                "description": request.config.description.strip(),
                "derivation": request.config.model_dump(mode="json"),
            }
        )
        if content_revision:
            metadata = {
                **source.metadata,
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "content_revision": content_revision,
                "obsolete_content": obsolete_content(source, self.storage),
                "last_update_task_id": task_id,
            }
        derived = replace(
            planned,
            dataset_version_id=version_id,
            samples=tuple(samples),
            metadata=metadata,
        )
        self.storage.write_json(
            layout.dataset_version_path,
            {
                "dataset_version_id": version_id,
                "dataset_id": source.dataset_id,
                "project_id": source.project_id,
                "task_type": source.task_type,
                "sample_count": len(samples),
                **metadata,
            },
        )
        self.storage.write_json(
            layout.categories_path,
            [
                {"category_id": c.category_id, "name": c.name}
                for c in planned.categories
            ],
        )
        for split, items in indexes.items():
            self.storage.write_json(
                f"{layout.indexes_dir}/{split}.json",
                {
                    "dataset_version_id": version_id,
                    "split": split,
                    "sample_count": len(items),
                    "samples": items,
                },
            )
        return derived
