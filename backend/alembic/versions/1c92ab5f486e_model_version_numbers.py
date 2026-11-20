"""为模型版本登记稳定的显示序号。"""

from collections import defaultdict
from datetime import datetime, timezone
import re

import sqlalchemy as sa
from alembic import op

revision = "1c92ab5f486e"
down_revision = "90ab3916f4cb"
branch_labels = None
depends_on = None


def _timestamp(value: object) -> float:
    """将不同格式的时间统一为可比较的 UTC 时间。"""
    if isinstance(value, str) and value:
        try:
            time = datetime.fromisoformat(value)
            if time.tzinfo is None:
                time = time.replace(tzinfo=timezone.utc)
            return time.timestamp()
        except (ValueError, OverflowError, OSError):
            pass
    return float("inf")


def _technical_name(name: str) -> bool:
    """识别既有自动生成的英文标识，保留已经可读的名称。"""
    return bool(re.fullmatch(r"[a-z0-9_.-]+", name) and (
        re.search(r"\d{8,}", name) or name.count("-") + name.count("_") >= 2
    ))


def _fill_display_names(bind, schema, models, latest) -> None:
    """为旧的技术名称登记易读的名称，保持项目内可区分。"""
    datasets = sa.Table("datasets", schema, autoload_with=bind)
    dataset_versions = sa.Table("dataset_versions", schema, autoload_with=bind)
    dataset_names = dict(bind.execute(sa.select(
        dataset_versions.c.dataset_version_id, datasets.c.display_name,
    ).join(datasets, sa.and_(dataset_versions.c.dataset_id == datasets.c.dataset_id,
                           dataset_versions.c.project_id == datasets.c.project_id))).all())
    labels = {
        "detection": "目标检测", "classification": "图像分类", "segmentation": "分割",
        "pose": "姿态估计", "obb": "旋转框检测", "anomaly": "异常检测",
    }
    used = defaultdict(set)
    pending = []
    for row in bind.execute(sa.select(models).order_by(models.c.model_id)).mappings():
        if row["project_id"] is None:
            continue
        key = row["project_id"]
        name = row["model_name"]
        metadata = dict(row["metadata_json"] or {})
        display_name = metadata.get("display_name")
        custom_name = display_name.strip() if isinstance(display_name, str) else ""
        if custom_name or not _technical_name(name):
            used[key].add((custom_name or name).strip().casefold())
            continue
        pending.append((row, metadata))
    for row, metadata in pending:
        key = row["project_id"]
        title = dataset_names.get(latest.get(row["model_id"])) or ""
        if not title or _technical_name(title):
            title = labels.get(row["task_type"], "视觉模型")
        scale = {"nano": "n", "small": "s", "medium": "m", "large": "l", "extra-large": "x"}.get(row["model_scale"], row["model_scale"])
        family = row["model_type"].upper()
        base = f"{title[:80]} {family}-{scale}"
        display_name = base
        index = 2
        while display_name.casefold() in used[key]:
            display_name = f"{base} · {index}"
            index += 1
        used[key].add(display_name.casefold())
        bind.execute(models.update().where(models.c.model_id == row["model_id"]).values(
            metadata_json={**metadata, "display_name": display_name},
        ))


def upgrade() -> None:
    """按可用登记时间及同模型父版本还原历史顺序，原有版本 ID 保持稳定。"""
    bind = op.get_bind()
    if "version_sequence" not in {col["name"] for col in sa.inspect(bind).get_columns("models")}:
        op.add_column("models", sa.Column("version_sequence", sa.Integer(), server_default="0", nullable=False))
    existing = "version_number" in {col["name"] for col in sa.inspect(bind).get_columns("model_versions")}
    if not existing:
        op.add_column("model_versions", sa.Column("version_number", sa.Integer(), server_default="1", nullable=False))
    schema = sa.MetaData()
    models = sa.Table("models", schema, autoload_with=bind)
    versions = sa.Table("model_versions", schema, autoload_with=bind)
    tasks = sa.Table("tasks", schema, autoload_with=bind)
    history = bind.execute(sa.select(
        versions, tasks.c.finished_at, tasks.c.created_at,
    ).select_from(versions.outerjoin(tasks, tasks.c.task_id == versions.c.training_task_id))).mappings()
    groups = defaultdict(list)
    for row in history:
        groups[row["model_id"]].append(row)

    def sort_key(row):
        """优先采用版本时间，其次采用关联训练任务时间。"""
        metadata = row["metadata_json"] or {}
        candidates = (metadata.get("registered_at"), metadata.get("created_at"), row["finished_at"], row["created_at"])
        return next((timestamp for value in candidates if (timestamp := _timestamp(value)) != float("inf")), float("inf")), row["model_version_id"]

    latest = {}
    for model_id, rows in groups.items():
        if existing:
            maximum = max(row["version_number"] for row in rows)
            latest[model_id] = next(row["dataset_version_id"] for row in rows if row["version_number"] == maximum)
        else:
            numbers = [(row["metadata_json"] or {}).get("version_number") for row in rows]
            if all(type(value) is int and value > 0 for value in numbers) and len(set(numbers)) == len(rows):
                assignments = list(zip(rows, numbers, strict=True))
            else:
                remaining = {row["model_version_id"]: row for row in sorted(rows, key=sort_key)}
                ordered = []
                while remaining:
                    free = [row for row in remaining.values() if row["parent_version_id"] not in remaining]
                    row = (free or list(remaining.values()))[0]
                    ordered.append(remaining.pop(row["model_version_id"]))
                assignments = list(zip(ordered, range(1, len(ordered) + 1), strict=True))
            for row, number in assignments:
                bind.execute(versions.update().where(versions.c.model_version_id == row["model_version_id"]).values(version_number=number))
            maximum = max(number for _, number in assignments)
            latest[model_id] = next(row["dataset_version_id"] for row, number in assignments if number == maximum)
        bind.execute(models.update().where(models.c.model_id == model_id, models.c.version_sequence < maximum).values(version_sequence=maximum))
    if "uq_model_versions_number" not in {index["name"] for index in sa.inspect(bind).get_indexes("model_versions")}:
        op.create_index("uq_model_versions_number", "model_versions", ["model_id", "version_number"], unique=True)
    _fill_display_names(bind, schema, models, latest)


def downgrade() -> None:
    """移除显示序号及计数器，维持资源 ID 与文件记录。"""
    op.drop_index("uq_model_versions_number", "model_versions")
    with op.batch_alter_table("model_versions") as batch:
        batch.drop_column("version_number")
    with op.batch_alter_table("models") as batch:
        batch.drop_column("version_sequence")
