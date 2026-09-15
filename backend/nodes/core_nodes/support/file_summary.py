"""通用文件增量归约与派生检查点，不识别生产字段。"""

import hashlib
from pathlib import Path
from uuid import uuid4

from backend.nodes.core_nodes.support.condition_expression import (
    evaluate_condition_expression,
)
from backend.nodes.core_nodes.support.logic import try_extract_value_by_path
from backend.nodes.core_nodes.support.rule_counting import validate_condition
from backend.service.application.runtime.io.jsonl import (
    MAX_SAFE_INTEGER,
    atomic_write_bytes,
    decode,
    encode,
    fail,
    read_records,
    sidecars,
)

MAX_CHECKPOINT_BYTES = 4 * 1024 * 1024


def _checkpoint_bytes(path: Path) -> bytes | None:
    """单次有界读取；超限派生状态保留前缀用于并发冲突核对。"""
    try:
        with path.open("rb") as stream:
            return stream.read(MAX_CHECKPOINT_BYTES + 1)
    except FileNotFoundError:
        return None


def validate_reducers(reducers: object) -> list[dict]:
    """校验字段归约规则，空数据也必须校验配置。"""
    if not isinstance(reducers, list) or not 1 <= len(reducers) <= 64:
        raise fail("Reducers 需要 1–64 条规则")
    keys = set()
    for rule in reducers:
        if not isinstance(rule, dict):
            raise fail("Reducer 必须是对象")
        key, operation = rule.get("output_key"), rule.get("operation")
        if not isinstance(key, str) or not key.strip() or key in keys:
            raise fail("Reducer output_key 必须非空且唯一")
        keys.add(key)
        if operation not in {"sum", "count", "min", "max", "last"}:
            raise fail("不支持的 Reducer operation")
        if operation != "count" and (
            not isinstance(rule.get("source_path"), str)
            or not rule["source_path"].strip()
        ):
            raise fail("Reducer source_path 必须非空")
        if rule.get("numeric_type", "integer") not in {"integer", "number"} or rule.get(
            "missing_policy", "error"
        ) not in {"error", "skip"}:
            raise fail("Reducer 数值类型或缺失策略无效")
    return reducers


def initial_totals(reducers: list[dict]) -> dict:
    """空聚合仅 sum/count 为零，其他操作尚无结果。"""
    return {
        r["output_key"]: 0 if r["operation"] in {"sum", "count"} else None
        for r in reducers
    }


def _number(value, numeric_type):
    """保持整数精度，拒绝 bool、数字字符串、非有限值和越界。"""
    import math

    if type(value) not in (int, float) or (
        type(value) is float and not math.isfinite(value)
    ):
        raise fail("Reducer 字段必须为有限数值")
    if numeric_type == "integer" and type(value) is not int:
        raise fail("整数归约不能接收小数")
    if type(value) is int and abs(value) > MAX_SAFE_INTEGER:
        raise fail("整数超过前端安全整数范围")
    return value


def reduce_record(totals: dict, record: dict, reducers: list[dict]) -> None:
    """纯归约操作，调用方持有本批独立状态。"""
    for rule in reducers:
        key, op = rule["output_key"], rule["operation"]
        if op == "count":
            totals[key] = _number(totals[key] + 1, "integer")
            continue
        exists, value = try_extract_value_by_path(root=record, path=rule["source_path"])
        if not exists or value is None:
            if rule.get("missing_policy", "error") == "skip":
                continue
            raise fail(f"Reducer 字段缺失：{rule['source_path']}")
        if op == "last":
            totals[key] = value
            continue
        kind = rule.get("numeric_type", "integer")
        value = _number(value, kind)
        previous = totals[key]
        result = (
            previous + value
            if op == "sum"
            else value
            if previous is None
            else (min(previous, value) if op == "min" else max(previous, value))
        )
        totals[key] = _number(result, kind)


def summarize(
    path: Path, state_path: Path, *, reducers: list, lock, condition=None, **options
) -> dict:
    """读取独立批次，在短检查点锁中进行 revision 校验后原子发布。"""
    reducers = validate_reducers(reducers)
    if condition is not None:
        validate_condition(condition)
    resolved = path.resolve()
    if state_path.resolve() in {resolved, *(p.resolve() for p in sidecars(resolved))}:
        raise fail("检查点不能覆盖日志或提交元数据")
    signature = hashlib.sha256(
        encode(
            dict(
                path=str(resolved),
                reducers=reducers,
                condition=condition,
                source_mode=options.get("source_mode", "managed"),
                version=1,
            )
        )
    ).hexdigest()
    # 先验证权威文件；损坏日志不得因检查点重建被降级为空数据。
    head_options = {**options, "max_records": 1}
    head = read_records(path, **head_options)
    source_end = head["snapshot_end"]
    previous_bytes = _checkpoint_bytes(state_path)
    state = None
    if previous_bytes is not None and len(previous_bytes) <= MAX_CHECKPOINT_BYTES:
        try:
            candidate = decode(previous_bytes)
            checksum = (
                candidate.get("checksum") if isinstance(candidate, dict) else None
            )
            body = candidate.get("body") if isinstance(candidate, dict) else None
            if (
                isinstance(body, dict)
                and hashlib.sha256(encode(body)).hexdigest() == checksum
                and isinstance(body.get("totals"), dict)
                and set(body["totals"]) == {r["output_key"] for r in reducers}
                and isinstance(body.get("cursor"), dict)
                and "latest" in body
            ):
                state = body
        except Exception as exc:
            from backend.service.application.errors import InvalidRequestError

            if not isinstance(exc, (InvalidRequestError, ValueError)):
                raise
    if not source_end:
        return dict(
            totals=initial_totals(reducers),
            latest=None,
            source=None,
            complete=True,
            status="empty",
        )
    if (
        state is None
        or state.get("signature") != signature
        or state.get("cursor", {}).get("generation") != source_end["generation"]
    ):
        state = dict(
            signature=signature,
            totals=initial_totals(reducers),
            latest=None,
            cursor=None,
            pending_end=None,
            revision=None,
        )
    totals = dict(state["totals"])
    latest = state["latest"]

    def consume(record: dict) -> None:
        """归约计入每条完整记录之间的时间预算。"""
        nonlocal latest
        if condition is None or evaluate_condition_expression(
            root_value=record,
            condition=condition,
            node_id="file-summary",
            context_label="record",
        ):
            reduce_record(totals, record, reducers)
            latest = record

    batch = read_records(
        path,
        cursor=state["cursor"],
        snapshot_end=state.get("pending_end"),
        on_record=consume,
        **options,
    )
    revision = (
        uuid4().hex
        if batch["records"] or not state.get("revision")
        else state["revision"]
    )
    updated = dict(
        signature=signature,
        totals=totals,
        latest=latest,
        cursor=batch["next_cursor"],
        pending_end=batch["snapshot_end"] if batch["has_more"] else None,
        revision=revision,
    )
    if updated != state:
        encoded = encode(
            dict(body=updated, checksum=hashlib.sha256(encode(updated)).hexdigest())
        )
        if len(encoded) > MAX_CHECKPOINT_BYTES:
            raise fail("汇总检查点超过 4 MiB，请减少 last 归约字段或记录大小")
        with lock as acquired:
            if not acquired:
                raise fail("检查点正在更新", "jsonl_checkpoint_busy")
            current_bytes = _checkpoint_bytes(state_path)
            if current_bytes != previous_bytes:
                raise fail("检查点已由另一调用更新", "jsonl_checkpoint_conflict")
            atomic_write_bytes(state_path, encoded)
    source = {
        **batch["next_cursor"],
        "snapshot_revision": revision,
        "complete": not batch["has_more"],
    }
    return dict(
        totals=totals,
        latest=latest,
        source=source,
        complete=not batch["has_more"],
        status="loading"
        if batch["has_more"]
        else "ready"
        if latest is not None
        else "empty",
    )
