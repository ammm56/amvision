"""数据集工作区读写仓储；分页查询不加载完整 DatasetVersion 聚合。"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import and_, exists, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from backend.service.application.errors import (
    InvalidRequestError,
    ResourceConflictError,
    ResourceNotFoundError,
)
from backend.contracts.datasets.sample_selection import DatasetSampleSelection
from backend.service.infrastructure.persistence.dataset_orm import (
    DatasetRecord,
    DatasetVersionRecord,
    DatasetCategoryRecord,
    DatasetSampleRecord,
    DatasetAnnotationRecord,
)


class DatasetCatalogRepository:
    """集中管理数据集信息及有界的版本、样本、标注查询。"""

    def __init__(self, session: Session) -> None:
        """session 由请求或 worker 的 Unit of Work 管理。"""
        self.session = session

    def count(self, project_id: str) -> int:
        """与数据集列表保持同一资源口径。"""
        return int(
            self.session.scalar(
                select(func.count())
                .select_from(DatasetRecord)
                .where(DatasetRecord.project_id == project_id)
            )
            or 0
        )

    def record_version_numbers(self, project_id: str, version_ids: list[str]) -> dict:
        """只读取单页记录引用的版本编号，不加载图片、标注或当前统计。"""
        if not version_ids:
            return {}
        rows = self.session.execute(
            select(
                DatasetVersionRecord.dataset_id,
                DatasetVersionRecord.dataset_version_id,
                DatasetVersionRecord.version_number,
            ).where(
                DatasetVersionRecord.project_id == project_id,
                DatasetVersionRecord.dataset_version_id.in_(version_ids),
            )
        )
        return {(row.dataset_id, row.dataset_version_id): row.version_number for row in rows}

    def ensure(
        self,
        project_id: str,
        dataset_id: str,
        task_type: str,
        created_at: str = "",
        *,
        display_name: str = "",
        description: str = "",
    ) -> None:
        """首次导入或直接保存版本时登记身份；同一数据集不混合不同任务类型。"""
        record = self.session.get(DatasetRecord, (project_id, dataset_id))
        if record is None:
            now = created_at or datetime.now(timezone.utc).isoformat()
            try:
                with self.session.begin_nested():
                    self.session.add(
                        DatasetRecord(
                            project_id=project_id,
                            dataset_id=dataset_id,
                            display_name=display_name or dataset_id,
                            description=description,
                            task_type=task_type,
                            created_at=now,
                            updated_at=now,
                            revision=uuid4().hex,
                        )
                    )
                    self.session.flush()
            except IntegrityError:
                # 并发首次导入可能已登记同一身份；重新读取并检查任务类型。
                record = self.session.get(
                    DatasetRecord, (project_id, dataset_id), populate_existing=True
                )
                if record is None:
                    raise
        if record is not None and record.task_type != task_type:
            raise ResourceConflictError(
                "数据集任务类型不一致，请选择其他数据集",
                details={"dataset_id": dataset_id},
            )
        if record is not None and created_at:
            # 新版本发布同步更新时间；条件更新避免并发旧版本把时间写回过去。
            # 名称/说明的 revision 不随版本发布变化，防止无关的元数据编辑冲突。
            self.session.execute(
                update(DatasetRecord)
                .where(
                    DatasetRecord.project_id == project_id,
                    DatasetRecord.dataset_id == dataset_id,
                    DatasetRecord.updated_at < created_at,
                )
                .values(updated_at=created_at)
            )

    @staticmethod
    def _metadata(record: DatasetRecord) -> dict:
        """输出可编辑的目录字段；不向接口泄漏 ORM 对象。"""
        return {
            name: getattr(record, name)
            for name in (
                "project_id",
                "dataset_id",
                "display_name",
                "description",
                "task_type",
                "created_at",
                "updated_at",
                "revision",
            )
        }

    def get(self, project_id: str, dataset_id: str) -> dict:
        """按项目和身份读取目录，避免跨项目同名混淆。"""
        record = self.session.get(DatasetRecord, (project_id, dataset_id))
        if record is None:
            raise ResourceNotFoundError("找不到指定的数据集")
        return self._metadata(record)

    def edit(
        self,
        project_id: str,
        dataset_id: str,
        *,
        display_name: str,
        description: str,
        revision: str,
    ) -> dict:
        """原子检查 revision 并更新信息，不更改版本或正在使用的引用。"""
        result = self.session.execute(
            update(DatasetRecord)
            .where(
                DatasetRecord.project_id == project_id,
                DatasetRecord.dataset_id == dataset_id,
                DatasetRecord.revision == revision,
            )
            .values(
                display_name=display_name,
                description=description,
                updated_at=datetime.now(timezone.utc).isoformat(),
                revision=uuid4().hex,
            )
        )
        if result.rowcount != 1:
            self.get(project_id, dataset_id)
            raise ResourceConflictError("数据集信息已被其他操作修改，请重新加载后保存")
        self.session.flush()
        self.session.expire_all()
        return self.get(project_id, dataset_id)

    def list(
        self,
        project_id: str,
        *,
        q: str = "",
        task_type: str = "",
        state: str = "",
        offset: int = 0,
        limit: int = 20,
    ) -> dict:
        """目录分页；最新版本按持久化序号排序，不按随机 id 或客户端时间排序。"""
        latest = (
            select(DatasetVersionRecord.dataset_version_id)
            .where(
                DatasetVersionRecord.project_id == DatasetRecord.project_id,
                DatasetVersionRecord.dataset_id == DatasetRecord.dataset_id,
            )
            .order_by(
                DatasetVersionRecord.version_number.desc(),
                DatasetVersionRecord.dataset_version_id.desc(),
            )
            .limit(1)
            .correlate(DatasetRecord)
            .scalar_subquery()
        )
        statement = select(DatasetRecord, latest.label("latest_id")).where(
            DatasetRecord.project_id == project_id
        )
        if q:
            statement = statement.where(
                or_(
                    DatasetRecord.display_name.icontains(q, autoescape=True),
                    DatasetRecord.dataset_id.icontains(q, autoescape=True),
                )
            )
        if task_type:
            statement = statement.where(DatasetRecord.task_type == task_type)
        if state:
            statement = statement.where(
                latest.is_not(None) if state == "available" else latest.is_(None)
            )
        total = (
            self.session.scalar(select(func.count()).select_from(statement.subquery()))
            or 0
        )
        rows = self.session.execute(
            statement.order_by(
                DatasetRecord.updated_at.desc(), DatasetRecord.dataset_id
            )
            .offset(offset)
            .limit(limit)
        ).all()
        summaries = {
            item["dataset_version_id"]: item
            for item in self.version_summaries(
                [row.latest_id for row in rows if row.latest_id]
            )
        }
        return {
            "items": [
                {
                    **self._metadata(row[0]),
                    "latest_version": summaries.get(row.latest_id),
                }
                for row in rows
            ],
            "total": total,
            "offset": offset,
            "limit": limit,
        }

    def _version_query(
        self,
        project_id: str,
        *,
        dataset_id: str = "",
        q: str = "",
        task_type: str = "",
    ):
        """构建项目内版本筛选，供分页及资源状态检查共用。"""
        statement = (
            select(DatasetVersionRecord.dataset_version_id)
            .outerjoin(
                DatasetRecord,
                and_(
                    DatasetRecord.project_id == DatasetVersionRecord.project_id,
                    DatasetRecord.dataset_id == DatasetVersionRecord.dataset_id,
                ),
            )
            .where(DatasetVersionRecord.project_id == project_id)
        )
        if dataset_id:
            statement = statement.where(DatasetVersionRecord.dataset_id == dataset_id)
        if q:
            statement = statement.where(
                or_(
                    DatasetRecord.display_name.icontains(q, autoescape=True),
                    DatasetVersionRecord.dataset_id.icontains(q, autoescape=True),
                    DatasetVersionRecord.dataset_version_id.icontains(
                        q, autoescape=True
                    ),
                )
            )
        if task_type:
            statement = statement.where(DatasetVersionRecord.task_type == task_type)
        return statement

    def version_candidates(self, project_id: str, **filters):
        """按版本顺序流式读取资源身份；不加载样本和标注。"""
        statement = self._version_query(project_id, **filters).with_only_columns(
            DatasetVersionRecord.dataset_version_id,
            DatasetVersionRecord.dataset_id,
            DatasetVersionRecord.project_id,
            DatasetVersionRecord.metadata_json.label("metadata"),
            exists().where(
                DatasetSampleRecord.dataset_version_id == DatasetVersionRecord.dataset_version_id
            ).label("has_samples"),
        )
        for row in self.session.execute(
            statement.order_by(
                DatasetVersionRecord.metadata_json["created_at"].as_string().desc()
                if not filters.get("dataset_id") else DatasetVersionRecord.version_number.desc(),
                DatasetVersionRecord.version_number.desc(),
                DatasetVersionRecord.dataset_version_id.desc(),
            ).execution_options(yield_per=100)
        ).mappings():
            yield dict(row)

    def versions(
        self, project_id: str, *, dataset_id: str = "", q: str = "",
        task_type: str = "", offset: int = 0, limit: int = 20,
    ) -> dict:
        """读取版本列表，单页最多由 API 限制为 100 条。"""
        statement = self._version_query(project_id, dataset_id=dataset_id, q=q, task_type=task_type)
        total = (
            self.session.scalar(select(func.count()).select_from(statement.subquery()))
            or 0
        )
        order = (
            [DatasetVersionRecord.version_number.desc()]
            if dataset_id else [
                DatasetVersionRecord.metadata_json["created_at"].as_string().desc(),
                DatasetVersionRecord.version_number.desc(),
            ]
        )
        ids = list(
            self.session.scalars(
                statement.order_by(
                    *order,
                    DatasetVersionRecord.dataset_version_id.desc(),
                )
                .offset(offset)
                .limit(limit)
            )
        )
        return {
            "items": self.version_summaries(ids),
            "total": total,
            "offset": offset,
            "limit": limit,
        }

    def _version_tasks(self, project_id: str, ids: list[str]):
        """返回当前项目中直接使用这些版本的训练、评估任务投影。"""
        from backend.service.infrastructure.persistence.task_orm import TaskRecordEntity as Task

        version = func.coalesce(
            Task.task_spec_json["dataset_version_id"].as_string(),
            Task.metadata_json["dataset_version_id"].as_string(),
        )
        return select(
            version.label("version_id"), Task.task_kind, Task.task_id, Task.display_name, Task.created_at
        ).where(
            Task.project_id == project_id, version.in_(ids),
            or_(Task.task_kind.endswith("-training"), Task.task_kind.endswith("-evaluation")),
        )

    def version_task_counts(self, project_id: str, ids: list[str]) -> dict[str, dict[str, int]]:
        """仅在查看版本来源时按当前页聚合，不读取任务载荷。"""
        counts = {key: {"training": 0, "evaluation": 0} for key in ids}
        if ids:
            tasks = self._version_tasks(project_id, ids).subquery()
            query = select(tasks.c.version_id, tasks.c.task_kind, func.count()).group_by(
                tasks.c.version_id, tasks.c.task_kind
            )
            for key, kind, count in self.session.execute(query):
                counts[key][kind.rsplit("-", 1)[1]] += count
        return counts

    def version_task_references(self, project_id: str, version_id: str, offset: int, limit: int) -> dict:
        """分页列出引用的任务，只返回可用于打开详情的轻量字段。"""
        tasks = self._version_tasks(project_id, [version_id]).subquery()
        rows = self.session.execute(
            select(tasks.c.task_id, tasks.c.task_kind, tasks.c.display_name, tasks.c.created_at)
            .order_by(tasks.c.created_at.desc(), tasks.c.task_id)
            .offset(offset).limit(limit + 1)
        ).mappings().all()
        return {"items": [dict(row) for row in rows[:limit]], "has_more": len(rows) > limit}

    def version_summaries(self, ids: list[str]) -> list[dict]:
        """仅聚合当前页版本的计数，不读取样本数组。"""
        if not ids:
            return []
        versions = self.session.scalars(
            select(DatasetVersionRecord).where(
                DatasetVersionRecord.dataset_version_id.in_(ids)
            )
        ).all()
        names = (
            {
                (r.project_id, r.dataset_id): r.display_name
                for r in self.session.scalars(
                    select(DatasetRecord).where(
                        or_(
                            *[
                                and_(
                                    DatasetRecord.project_id == v.project_id,
                                    DatasetRecord.dataset_id == v.dataset_id,
                                )
                                for v in versions
                            ]
                        )
                    )
                )
            }
            if versions
            else {}
        )
        splits: dict[str, dict[str, int]] = {}
        for version, split, count in self.session.execute(
            select(
                DatasetSampleRecord.dataset_version_id,
                DatasetSampleRecord.split,
                func.count(),
            )
            .where(DatasetSampleRecord.dataset_version_id.in_(ids))
            .group_by(DatasetSampleRecord.dataset_version_id, DatasetSampleRecord.split)
        ):
            splits.setdefault(version, {})[split] = count
        categories = dict(
            self.session.execute(
                select(DatasetCategoryRecord.dataset_version_id, func.count())
                .where(DatasetCategoryRecord.dataset_version_id.in_(ids))
                .group_by(DatasetCategoryRecord.dataset_version_id)
            ).all()
        )
        objects = dict(
            self.session.execute(
                select(DatasetSampleRecord.dataset_version_id, func.count())
                .join(
                    DatasetAnnotationRecord,
                    DatasetAnnotationRecord.sample_id == DatasetSampleRecord.sample_id,
                )
                .where(DatasetSampleRecord.dataset_version_id.in_(ids))
                .group_by(DatasetSampleRecord.dataset_version_id)
            ).all()
        )
        result = {
            v.dataset_version_id: {
                "dataset_version_id": v.dataset_version_id,
                "version_number": v.version_number,
                "dataset_id": v.dataset_id,
                "project_id": v.project_id,
                "display_name": names.get((v.project_id, v.dataset_id), v.dataset_id),
                "task_type": v.task_type,
                "created_at": (v.metadata_json or {}).get("created_at"),
                "sample_count": sum(splits.get(v.dataset_version_id, {}).values()),
                "object_count": objects.get(v.dataset_version_id, 0),
                "category_count": categories.get(v.dataset_version_id, 0),
                "split_counts": splits.get(v.dataset_version_id, {}),
                "metadata": dict(v.metadata_json or {}),
            }
            for v in versions
        }
        return [result[key] for key in ids if key in result]

    def version(self, dataset_id: str, version_id: str) -> dict:
        """读取单版本身份与轻量统计，供路由校验项目权限。"""
        items = self.version_summaries([version_id])
        if not items or items[0]["dataset_id"] != dataset_id:
            raise ResourceNotFoundError("找不到指定的数据集版本")
        result = items[0]
        # 目录统计和划分总数包含未指定类别的对象，不能累加各类别图像数。
        result["split_object_counts"] = dict(self.session.execute(
            select(DatasetSampleRecord.split, func.count())
            .join(DatasetAnnotationRecord, DatasetAnnotationRecord.sample_id == DatasetSampleRecord.sample_id)
            .where(DatasetSampleRecord.dataset_version_id == version_id)
            .group_by(DatasetSampleRecord.split)
        ).all())
        # 来源版本仅返回同一数据集中的序号；已删除的来源不能伪造仍可访问。
        parent_id = str(result["metadata"].get("parent_version_id") or "")
        parent = self.session.get(DatasetVersionRecord, parent_id) if parent_id else None
        result["parent_version_number"] = (
            parent.version_number if parent is not None
            and parent.project_id == result["project_id"]
            and parent.dataset_id == dataset_id else None
        )
        result["dataset"] = self.get(result["project_id"], dataset_id)
        result["categories"] = [
            {"category_id": row.category_id, "name": row.name}
            for row in self.session.scalars(
                select(DatasetCategoryRecord)
                .where(DatasetCategoryRecord.dataset_version_id == version_id)
                .order_by(DatasetCategoryRecord.category_id)
            )
        ]
        return result

    def category_statistics(self, version_id: str) -> dict:
        """按真实标注聚合图像数及对象数；一张图可归属多个类别。"""
        a, s = DatasetAnnotationRecord, DatasetSampleRecord
        rows = self.session.execute(
            select(
                a.category_id,
                s.split,
                func.count(a.annotation_id),
                func.count(func.distinct(s.sample_id)),
            )
            .join(s, s.sample_id == a.sample_id)
            .where(s.dataset_version_id == version_id)
            .group_by(a.category_id, s.split)
        ).all()
        counts: dict[int, dict] = {}
        for category_id, split, objects, images in rows:
            item = counts.setdefault(
                category_id, {"object_count": 0, "sample_count": 0, "split_objects": {}}
            )
            item["object_count"] += objects
            item["sample_count"] += images
            item["split_objects"][split] = objects
        categories = self.session.scalars(
            select(DatasetCategoryRecord)
            .where(DatasetCategoryRecord.dataset_version_id == version_id)
            .order_by(DatasetCategoryRecord.category_id)
        )
        return {
            "items": [
                {
                    "category_id": c.category_id,
                    "name": c.name,
                    **counts.get(
                        c.category_id,
                        {"object_count": 0, "sample_count": 0, "split_objects": {}},
                    ),
                }
                for c in categories
            ]
        }

    def import_report(self, version_id: str) -> dict:
        """读取真实导入检查报告；记录已删时不伪造通过结果。"""
        from backend.service.infrastructure.persistence.dataset_import_orm import (
            DatasetImportRecord,
        )

        version = self.session.get(DatasetVersionRecord, version_id)
        metadata = dict(version.metadata_json or {}) if version else {}
        if "validation_report" in metadata:
            source_id = metadata.get("source_import_id")
            # 已清理的导入保留报告快照，同时移除失效的详情跳转。
            record_id = self.session.scalar(
                select(DatasetImportRecord.dataset_import_id).where(
                    DatasetImportRecord.dataset_import_id == source_id
                )
            ) if source_id else None
            return {
                "available": True,
                "dataset_import_id": record_id,
                "checked_at": metadata.get("created_at"),
                "report": metadata["validation_report"],
            }
        record = self.session.scalar(
            select(DatasetImportRecord)
            .where(DatasetImportRecord.dataset_version_id == version_id)
            .order_by(DatasetImportRecord.created_at.desc())
            .limit(1)
        )
        if record is None:
            return {"available": False, "report": None, "checked_at": None}
        return {
            "available": True,
            "dataset_import_id": record.dataset_import_id,
            "checked_at": record.created_at,
            "report": dict(record.validation_report_json or {}),
        }

    def version_identity(self, dataset_id: str, version_id: str) -> dict:
        """媒体及分页请求只读取身份，不重复聚合整版本计数。"""
        record = self.session.get(DatasetVersionRecord, version_id)
        if record is None or record.dataset_id != dataset_id:
            raise ResourceNotFoundError("找不到指定的数据集版本")
        return {
            "dataset_id": record.dataset_id,
            "project_id": record.project_id,
            "dataset_version_id": version_id,
            "task_type": record.task_type,
            "metadata": dict(record.metadata_json or {}),
        }

    @staticmethod
    def _sample(record: DatasetSampleRecord, *, annotations: bool) -> dict:
        """保留原始像素坐标及类型，不把人工标注伪装为模型预测。"""
        result = {
            name: getattr(record, name)
            for name in (
                "sample_id",
                "image_id",
                "file_name",
                "width",
                "height",
                "split",
                "dataset_version_id",
            )
        }
        result["metadata"] = dict(record.metadata_json or {})
        if annotations:
            result["annotations"] = [
                {
                    "annotation_id": a.annotation_id,
                    "annotation_type": a.annotation_type or "detection",
                    "category_id": a.category_id,
                    "bbox_xywh": [a.bbox_x, a.bbox_y, a.bbox_w, a.bbox_h]
                    if a.bbox_x is not None
                    else None,
                    "segmentation": a.segmentation_json,
                    "keypoints": a.keypoints_json,
                    "polygon_xy": a.polygon_xy_json,
                    "area": a.area,
                    "iscrowd": a.iscrowd,
                    "is_anomalous": a.is_anomalous,
                    "mask_file_name": a.mask_file_name,
                    "metadata": dict(a.metadata_json or {}),
                }
                for a in record.annotations
            ]
        return result

    def samples(
        self,
        version_id: str,
        *,
        q: str = "",
        split: str = "",
        category_id: int | None = None,
        annotation_state: str = "",
        sort: str = "image_id",
        offset: int = 0,
        limit: int = 24,
    ) -> dict:
        """过滤样本后分页，仅加载本页标注；exists 避免多对象重复计数。"""
        statement = select(DatasetSampleRecord).where(
            *self._sample_filters(
                version_id,
                q=q,
                split=split,
                category_id=category_id,
                annotation_state=annotation_state,
            )
        )
        total = (
            self.session.scalar(select(func.count()).select_from(statement.subquery()))
            or 0
        )
        # 排序字段采用白名单；同名图片以样本 ID 稳定分页，不丢失重复文件。
        order = {
            "filename": func.lower(DatasetSampleRecord.file_name).asc(),
            "filename_desc": func.lower(DatasetSampleRecord.file_name).desc(),
        }.get(sort, DatasetSampleRecord.image_id.asc())
        rows = self.session.scalars(
            statement.options(selectinload(DatasetSampleRecord.annotations))
            .order_by(order, DatasetSampleRecord.sample_id)
            .offset(offset)
            .limit(limit)
        ).all()
        return {
            "items": [self._sample(row, annotations=True) for row in rows],
            "total": total,
            "offset": offset,
            "limit": limit,
        }

    @staticmethod
    def _sample_filters(
        version_id: str,
        *,
        q: str = "",
        split: str = "",
        category_id: int | None = None,
        annotation_state: str = "",
    ) -> list:
        """列表与选择汇总共用条件，避免两套筛选口径。"""
        conditions = [DatasetSampleRecord.dataset_version_id == version_id]
        if q:
            conditions.append(
                or_(
                    DatasetSampleRecord.file_name.icontains(q, autoescape=True),
                    DatasetSampleRecord.sample_id.icontains(q, autoescape=True),
                )
            )
        if split:
            conditions.append(DatasetSampleRecord.split == split)
        annotated = exists(
            select(DatasetAnnotationRecord.annotation_id).where(
                DatasetAnnotationRecord.sample_id == DatasetSampleRecord.sample_id
            )
        )
        if annotation_state:
            conditions.append(
                annotated if annotation_state == "annotated" else ~annotated
            )
        if category_id is not None:
            conditions.append(
                exists(
                    select(DatasetAnnotationRecord.annotation_id).where(
                        DatasetAnnotationRecord.sample_id
                        == DatasetSampleRecord.sample_id,
                        DatasetAnnotationRecord.category_id == category_id,
                    )
                )
            )
        return conditions

    def selection_summary(self, version_id: str, raw: dict) -> dict:
        """SQL 统计选择，不返回或加载全部筛选结果的 ID 和标注。"""
        selection = DatasetSampleSelection.model_validate(raw)
        conditions = self._sample_filters(
            version_id, **selection.model_dump(exclude={"mode", "sample_ids"})
        )
        if selection.mode == "ids":
            conditions.append(DatasetSampleRecord.sample_id.in_(selection.sample_ids))
        splits = dict(
            self.session.execute(
                select(DatasetSampleRecord.split, func.count())
                .where(*conditions)
                .group_by(DatasetSampleRecord.split)
            ).all()
        )
        total = sum(splits.values())
        if selection.mode == "ids" and total != len(selection.sample_ids):
            raise InvalidRequestError("选择包含不属于当前版本的样本")
        return {"sample_count": total, "split_counts": splits}

    def selected_ids(self, version_id: str, raw: dict) -> set[str]:
        """后台操作复用数据库筛选，避免 Unicode 筛选与页面不一致。"""
        selection = DatasetSampleSelection.model_validate(raw)
        conditions = self._sample_filters(
            version_id, **selection.model_dump(exclude={"mode", "sample_ids"})
        )
        if selection.mode == "ids":
            conditions.append(DatasetSampleRecord.sample_id.in_(selection.sample_ids))
        ids = set(
            self.session.scalars(
                select(DatasetSampleRecord.sample_id).where(*conditions)
            )
        )
        if selection.mode == "ids" and len(ids) != len(selection.sample_ids):
            raise InvalidRequestError("选择包含不属于当前版本的样本")
        return ids

    def jobs(
        self, project_id: str, version_id: str, *, offset: int = 0, limit: int = 20, operation: str = ""
    ) -> dict:
        """只加载本页摘要；报告在详情按需读取。"""
        from backend.service.infrastructure.persistence.task_orm import (
            TaskRecordEntity as Task,
        )

        statement = select(Task).where(
            Task.project_id == project_id,
            Task.task_kind == "dataset-workspace",
            Task.task_spec_json["dataset_version_id"].as_string() == version_id,
        )
        if operation:
            statement = statement.where(Task.task_spec_json["operation"].as_string() == operation)
        total = (
            self.session.scalar(select(func.count()).select_from(statement.subquery()))
            or 0
        )
        rows = self.session.scalars(
            statement.order_by(Task.created_at.desc(), Task.task_id)
            .offset(offset)
            .limit(limit)
        )
        return {
            "items": [
                {
                    "task_id": row.task_id,
                    "operation": row.task_spec_json["operation"],
                    "state": row.state,
                    "created_at": row.created_at,
                    "finished_at": row.finished_at,
                    "progress": row.progress_json,
                    "error_message": row.error_message,
                }
                for row in rows
            ],
            "total": total,
            "offset": offset,
            "limit": limit,
        }

    def sample(self, version_id: str, sample_id: str) -> dict:
        """精确读取当前版本内样本，不能用其他版本的样本 ID 绕过边界。"""
        record = self.session.scalar(
            select(DatasetSampleRecord)
            .options(selectinload(DatasetSampleRecord.annotations))
            .where(
                DatasetSampleRecord.dataset_version_id == version_id,
                DatasetSampleRecord.sample_id == sample_id,
            )
        )
        if record is None:
            raise ResourceNotFoundError("找不到指定的样本")
        return self._sample(record, annotations=True)

    def file_samples(
        self, version_id: str, path: str, *, offset: int = 0, limit: int = 20
    ) -> dict:
        """归一化版本文件按登记键关联；不猜测来源文件名是否一一对应。"""
        from pathlib import PurePosixPath

        parts = PurePosixPath(path).parts
        model = DatasetSampleRecord
        statement = select(model).where(model.dataset_version_id == version_id)
        if len(parts) == 3 and parts[0] == "samples" and parts[-1].endswith(".json"):
            statement = statement.where(
                model.sample_id == parts[-1][:-5], model.split == parts[1]
            )
        elif (
            len(parts) == 2
            and parts[0] == "indexes"
            and parts[-1] in {"train.json", "val.json", "test.json"}
        ):
            statement = statement.where(model.split == parts[-1][:-5])
        elif path in {"manifests/dataset-version.json", "manifests/categories.json"}:
            pass
        elif parts and parts[0] == "images":
            statement = statement.where(
                model.metadata_json["image_object_key"].as_string() == path
            )
        else:
            return {"items": [], "total": 0, "offset": offset, "limit": limit}
        total = (
            self.session.scalar(select(func.count()).select_from(statement.subquery()))
            or 0
        )
        rows = self.session.scalars(
            statement.options(selectinload(model.annotations))
            .order_by(model.image_id, model.sample_id)
            .offset(offset)
            .limit(limit)
        )
        return {
            "items": [self._sample(row, annotations=True) for row in rows],
            "total": total,
            "offset": offset,
            "limit": limit,
        }

    def records(
        self,
        project_id: str,
        kind: str,
        *,
        q: str = "",
        status: str = "",
        created_after: str = "",
        file_state: str = "",
        offset: int = 0,
        limit: int = 20,
    ) -> dict:
        """导入导出执行记录独立分页，终态历史不会挤占全部页面。"""
        from backend.service.infrastructure.persistence.dataset_import_orm import (
            DatasetImportRecord,
        )
        from backend.service.infrastructure.persistence.dataset_export_orm import (
            DatasetExportRecord,
        )
        from backend.service.infrastructure.persistence.dataset_import_repository import (
            SqlAlchemyDatasetImportRepository,
        )
        from backend.service.infrastructure.persistence.dataset_export_repository import (
            SqlAlchemyDatasetExportRepository,
        )

        model = DatasetImportRecord if kind == "imports" else DatasetExportRecord
        repository = (
            SqlAlchemyDatasetImportRepository(self.session)
            if kind == "imports"
            else SqlAlchemyDatasetExportRepository(self.session)
        )
        statement = (
            select(model)
            .outerjoin(
                DatasetRecord,
                and_(
                    DatasetRecord.project_id == model.project_id,
                    DatasetRecord.dataset_id == model.dataset_id,
                ),
            )
            .where(model.project_id == project_id)
        )
        if q:
            # 文件名检索使用 ORM JSON 表达式，兼容 SQLite/MySQL/PostgreSQL。
            file_name = model.metadata_json["source_file_name" if kind == "imports" else "package_file_name"].as_string()
            statement = statement.where(
                or_(
                    model.dataset_id.icontains(q, autoescape=True),
                    DatasetRecord.display_name.icontains(q, autoescape=True),
                    file_name.icontains(q, autoescape=True),
                    *( [model.package_path.icontains(q, autoescape=True)] if kind == "imports" else [] ),
                )
            )
        if status:
            statement = statement.where(model.status == status)
        if created_after:
            statement = statement.where(model.created_at >= created_after)
        if kind == "exports" and file_state:
            cleaned = model.metadata_json["files_cleaned_at"].as_string().is_not(None)
            filters = {
                "cleaned": cleaned,
                "ready": and_(~cleaned, model.status == "completed"),
                "generating": and_(~cleaned, model.status.in_(["queued", "running"])),
                "not_generated": and_(~cleaned, model.status.in_(["failed", "cancelled"])),
            }
            statement = statement.where(filters[file_state])
        total = (
            self.session.scalar(select(func.count()).select_from(statement.subquery()))
            or 0
        )
        identity = (
            model.dataset_import_id if kind == "imports" else model.dataset_export_id
        )
        records = self.session.scalars(
            statement.order_by(model.created_at.desc(), identity)
            .offset(offset)
            .limit(limit)
        ).all()
        return {
            "items": [repository._to_domain(row) for row in records],
            "total": total,
            "offset": offset,
            "limit": limit,
        }
