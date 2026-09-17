"""单机受管理 JSONL：短写锁、持久提交边界和有界读取。"""

from __future__ import annotations

import hashlib
import json
import math
import os
import time
from dataclasses import dataclass
from collections.abc import Callable
from contextlib import AbstractContextManager
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from backend.service.application.errors import InvalidRequestError
from backend.service.application.runtime.io.atomic_files import atomic_write_bytes

MAX_RECORD_BYTES = 1024 * 1024
DEFAULT_READ_BYTES = 4 * MAX_RECORD_BYTES
DEFAULT_READ_RECORDS = 1000
DEFAULT_READ_MS = 100
MAX_SAFE_INTEGER = 2**53 - 1


class Commit(BaseModel):
    """原子发布的日志身份和提交位置，不含业务字段。"""

    model_config = ConfigDict(extra="forbid", strict=True)
    format_id: str = "amvision.jsonl-commit.v1"
    generation: str
    device: int
    inode: int
    sequence: int = Field(ge=0, le=MAX_SAFE_INTEGER)
    committed_offset: int = Field(ge=0)
    last_operation: str | None = None
    last_digest: str | None = None


class Intent(BaseModel):
    """仅恢复当前物理追加所需的写意图。"""

    model_config = ConfigDict(extra="forbid", strict=True)
    generation: str
    operation: str
    offset: int = Field(ge=0)
    sequence: int = Field(ge=1, le=MAX_SAFE_INTEGER)
    length: int = Field(gt=0, le=MAX_RECORD_BYTES)
    digest: str


def fail(message: str, code: str = "jsonl_invalid") -> InvalidRequestError:
    """构造稳定文件错误，调用方不得把失败转成空记录。"""
    return InvalidRequestError(message, details={"error_code": code})


def encode(value: object) -> bytes:
    """严格编码 JSON，拒绝 NaN、Infinity 和无法序列化对象。"""
    try:
        return json.dumps(
            value, ensure_ascii=False, allow_nan=False, separators=(",", ":")
        ).encode("utf-8")
    except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
        raise fail("值不是有效 JSON") from exc


def decode(content: bytes) -> object:
    """严格解析 UTF-8 JSON，不接受非有限常量。"""

    def invalid_constant(value):
        raise ValueError(value)

    def finite_float(value):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError(value)
        return number

    try:
        return json.loads(
            content, parse_constant=invalid_constant, parse_float=finite_float
        )
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise fail("JSONL 内容损坏") from exc


def sidecars(path: Path) -> tuple[Path, Path]:
    """返回固定后缀的提交元数据和未完成意图路径。"""
    if path.name.endswith((".commit.json", ".intent.json")):
        raise fail("日志路径不能使用协议元数据后缀")
    return Path(str(path) + ".commit.json"), Path(str(path) + ".intent.json")


def read_small(path: Path, *, limit: int = DEFAULT_READ_BYTES) -> object:
    """读取有界控制文件或检查点。"""
    with path.open("rb") as stream:
        content = stream.read(limit + 1)
    if len(content) > limit:
        raise fail("控制文件超过大小限制")
    return decode(content)


def _commit(path: Path) -> Commit:
    """核对协议版本和实际文件身份。"""
    try:
        result = Commit.model_validate(read_small(sidecars(path)[0]))
        stat = path.stat()
    except FileNotFoundError as exc:
        raise fail(
            "JSONL 提交文件缺失，需要校验重建", "jsonl_rebuild_required"
        ) from exc
    except ValidationError as exc:
        raise fail("JSONL 提交元数据缺失或无效") from exc
    if stat.st_size == 0 and (
        result.committed_offset != 0
        or (stat.st_dev, stat.st_ino) != (result.device, result.inode)
    ):
        raise fail("JSONL 已清空，需要开始新记录", "jsonl_rebuild_required")
    if result.format_id != "amvision.jsonl-commit.v1" or (stat.st_dev, stat.st_ino) != (
        result.device,
        result.inode,
    ):
        raise fail("JSONL 文件身份已变化")
    if stat.st_size < result.committed_offset:
        raise fail("JSONL 已提交内容被截断")
    return result


def _publish(path: Path, commit: Commit) -> None:
    """原子发布；异常时读回确认，避免已提交被误报未提交。"""
    target = sidecars(path)[0]
    try:
        atomic_write_bytes(target, encode(commit.model_dump()))
    except OSError:
        if not target.exists() or read_small(target) != commit.model_dump():
            raise


def _clear_intent(path: Path) -> None:
    """提交后清理可延后，保留意图不会重复追加。"""
    try:
        sidecars(path)[1].unlink(missing_ok=True)
    except OSError:
        pass


def _rebuild_commit(
    path: Path, *, check_control: Callable[[], None] | None = None
) -> Commit:
    """调用方持写锁；逐行校验现存日志，重建丢失的元数据或清空后的新代次。"""
    intent_path = sidecars(path)[1]
    started = time.monotonic()
    sequence = 0
    with path.open("rb") as stream:
        before = os.fstat(stream.fileno())
        if before.st_size and intent_path.exists():
            raise fail("提交文件缺失且存在未完成写入，不能自动判定提交边界")
        while stream.tell() < before.st_size:
            if check_control:
                check_control()
            if time.monotonic() - started > 30:
                raise fail(
                    "JSONL 提交文件重建超过 30 秒，未修改原日志",
                    "jsonl_rebuild_timeout",
                )
            line = stream.readline(MAX_RECORD_BYTES + 1)
            if not line.endswith(b"\n") or len(line) > MAX_RECORD_BYTES:
                raise fail("JSONL 存在不完整或超限记录，不能重建提交文件")
            if not isinstance(decode(line), dict):
                raise fail("JSONL 每条记录必须为对象")
            sequence += 1
        after = path.stat()
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        ):
            raise fail("重建期间 JSONL 被修改，请在清理完成后重新执行")
    if check_control:
        check_control()
    # 空日志视为显式清理，旧意图不得应用于新日志；删除失败须中止。
    if not before.st_size:
        intent_path.unlink(missing_ok=True)
    commit = Commit(
        generation=uuid4().hex,
        device=before.st_dev,
        inode=before.st_ino,
        sequence=sequence,
        committed_offset=before.st_size,
    )
    _publish(path, commit)
    return commit


def _load_or_rebuild_commit(
    path: Path, *, check_control: Callable[[], None] | None = None
) -> Commit:
    """仅在可识别的清理情形恢复，格式损坏与非空文件替换仍明确失败。"""
    try:
        return _commit(path)
    except InvalidRequestError as exc:
        if exc.details.get("error_code") != "jsonl_rebuild_required":
            raise
    return _rebuild_commit(path, check_control=check_control)


def _recover(path: Path, commit: Commit) -> Commit:
    """调用方已持有路径锁；只恢复核对过的未提交尾部。"""
    intent_path = sidecars(path)[1]
    if not intent_path.exists():
        if path.stat().st_size != commit.committed_offset:
            raise fail("JSONL 有无法识别的未提交尾部")
        return commit
    try:
        intent = Intent.model_validate(read_small(intent_path))
    except ValidationError as exc:
        raise fail("JSONL 写意图无效") from exc
    if intent.generation != commit.generation:
        raise fail("JSONL 写意图来源冲突")
    if commit.sequence == intent.sequence and commit.last_operation == intent.operation:
        if (
            commit.committed_offset != intent.offset + intent.length
            or commit.last_digest != intent.digest
            or path.stat().st_size != commit.committed_offset
        ):
            raise fail("JSONL 已提交意图冲突")
        _clear_intent(path)
        return commit
    if (
        intent.sequence != commit.sequence + 1
        or intent.offset != commit.committed_offset
    ):
        raise fail("JSONL 写意图提交边界冲突")
    with path.open("r+b") as stream:
        stream.seek(intent.offset)
        tail = stream.read(intent.length + 1)
        if len(tail) > intent.length:
            raise fail("JSONL 写意图后存在未知内容")
        if len(tail) == intent.length:
            if hashlib.sha256(tail).hexdigest() != intent.digest or not tail.endswith(
                b"\n"
            ):
                raise fail("JSONL 尾部摘要不符")
            decode(tail)
            stream.flush()
            os.fsync(stream.fileno())
            commit = commit.model_copy(
                update=dict(
                    sequence=intent.sequence,
                    committed_offset=intent.offset + intent.length,
                    last_operation=intent.operation,
                    last_digest=intent.digest,
                )
            )
            _publish(path, commit)
        else:
            stream.truncate(commit.committed_offset)
            stream.flush()
            os.fsync(stream.fileno())
    _clear_intent(path)
    return commit


@dataclass(frozen=True)
class PreparedRecord:
    """锁外完成编码和摘要的不可变记录。"""

    payload: bytes
    digest: str


def prepare_record(value: dict) -> PreparedRecord:
    """序列化和大小检查不占用写锁。"""
    if not isinstance(value, dict):
        raise fail("Append JSONL 需要对象，不能输入 JSON 字符串")
    payload = encode(value) + b"\n"
    if len(payload) > MAX_RECORD_BYTES:
        raise fail("JSONL 单条记录超过 1 MiB")
    return PreparedRecord(payload, hashlib.sha256(payload).hexdigest())


def append_record(
    path: Path,
    value: dict | PreparedRecord,
    *,
    operation: str,
    check_control: Callable[[], None] | None = None,
) -> dict:
    """在调用方的短路径锁内追加一条对象，新调用使用不同 operation。"""
    prepared = value if isinstance(value, PreparedRecord) else prepare_record(value)
    payload, digest = prepared.payload, prepared.digest
    _, intent_path = sidecars(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        # 删除主日志就是开始新日志；残留提交文件不阻止后续写入。
        with path.open("xb") as stream:
            stream.flush()
            os.fsync(stream.fileno())
        commit = _rebuild_commit(path, check_control=check_control)
    else:
        commit = _load_or_rebuild_commit(path, check_control=check_control)
    commit = _recover(path, commit)
    if commit.last_operation == operation:
        if commit.last_digest != digest:
            raise fail("同一物理追加身份的内容不一致")
        return {**commit.model_dump(), "write_state": "committed"}
    intent = Intent(
        generation=commit.generation,
        operation=operation,
        offset=commit.committed_offset,
        sequence=commit.sequence + 1,
        length=len(payload),
        digest=digest,
    )
    atomic_write_bytes(intent_path, encode(intent.model_dump()))
    with path.open("ab") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    commit = commit.model_copy(
        update=dict(
            sequence=intent.sequence,
            committed_offset=intent.offset + intent.length,
            last_operation=operation,
            last_digest=digest,
        )
    )
    _publish(path, commit)
    _clear_intent(path)
    return {**commit.model_dump(), "write_state": "committed"}


def read_records(
    path: Path,
    *,
    cursor: dict | None = None,
    source_mode: str = "managed",
    max_records: int = DEFAULT_READ_RECORDS,
    max_bytes: int = DEFAULT_READ_BYTES,
    max_ms: int = DEFAULT_READ_MS,
    allow_missing: bool = False,
    snapshot_end: dict | None = None,
    check_control: Callable[[], None] | None = None,
    on_record: Callable[[dict], None] | None = None,
    repair_lock: Callable[[], AbstractContextManager[bool]] | None = None,
) -> dict:
    """正常读取不持写锁；repair_lock 仅用于清理后的元数据重建。"""
    if source_mode not in {"managed", "snapshot"}:
        raise fail("source_mode 必须为 managed 或 snapshot")
    if check_control:
        check_control()
    if (
        type(allow_missing) is not bool
        or (cursor is not None and not isinstance(cursor, dict))
        or (snapshot_end is not None and not isinstance(snapshot_end, dict))
    ):
        raise fail("JSONL 读取参数类型无效")
    for number, upper in (
        (max_records, 100_000),
        (max_bytes, 64 * MAX_RECORD_BYTES),
        (max_ms, 5000),
    ):
        if type(number) is not int or not 1 <= number <= upper:
            raise fail("JSONL 读取预算无效")
    if not path.exists():
        if allow_missing:
            return dict(
                records=[],
                next_cursor=None,
                snapshot_end=None,
                has_more=False,
                status="missing",
            )
        raise fail("JSONL 文件不存在", "jsonl_missing")
    commit = None
    if source_mode == "managed":
        try:
            commit = _commit(path)
        except InvalidRequestError as exc:
            if (
                exc.details.get("error_code") != "jsonl_rebuild_required"
                or repair_lock is None
            ):
                raise
            # 只有恢复需要写锁；正常读取仍不获取生产写锁。
            with repair_lock() as acquired:
                if not acquired:
                    raise fail("JSONL 正在写入，暂不能重建提交文件", "jsonl_busy")
                commit = _load_or_rebuild_commit(path, check_control=check_control)
    with path.open("rb") as stream:
        before = os.fstat(stream.fileno())
        identity = (
            f"{before.st_dev}:{before.st_ino}:{before.st_size}:{before.st_mtime_ns}"
        )
        source = dict(
            generation=commit.generation if commit else identity,
            offset=commit.committed_offset if commit else before.st_size,
            sequence=commit.sequence if commit else None,
        )
        if commit and (before.st_dev, before.st_ino) != (commit.device, commit.inode):
            raise fail("读取时 JSONL 身份变化")
        end = snapshot_end or source
        if (
            end.get("generation") != source["generation"]
            or type(end.get("offset")) is not int
            or not 0 <= end["offset"] <= source["offset"]
        ):
            raise fail("JSONL snapshot_end 无效或来源已变化")
        position = cursor or dict(generation=source["generation"], offset=0, sequence=0)
        if (
            position.get("generation") != source["generation"]
            or type(position.get("offset")) is not int
            or not 0 <= position["offset"] <= end["offset"]
        ):
            raise fail("JSONL cursor 无效或来源已变化")
        if type(position.get("sequence")) is not int or position["sequence"] < 0:
            raise fail("JSONL cursor sequence 无效")
        offset, sequence = position["offset"], position["sequence"]
        if offset:
            stream.seek(offset - 1)
            if stream.read(1) != b"\n":
                raise fail("JSONL cursor 不在完整行边界")
        stream.seek(offset)
        rows, consumed = [], 0
        started = time.monotonic()
        while offset < end["offset"] and len(rows) < max_records:
            if check_control:
                check_control()
            if rows and (
                consumed >= max_bytes or (time.monotonic() - started) * 1000 >= max_ms
            ):
                break
            line = stream.readline(min(MAX_RECORD_BYTES + 1, end["offset"] - offset))
            if not line or not line.endswith(b"\n") or len(line) > MAX_RECORD_BYTES:
                raise fail("JSONL 存在不完整或超限记录")
            if len(line) > max_bytes:
                raise fail("单条 JSONL 超过本次 max_bytes")
            if consumed + len(line) > max_bytes:
                break
            row = decode(line)
            if not isinstance(row, dict):
                raise fail("JSONL 每条记录必须为对象")
            if on_record:
                on_record(row)
            rows.append(row)
            consumed += len(line)
            offset += len(line)
            sequence += 1
        after = path.stat()
        if (before.st_dev, before.st_ino) != (
            after.st_dev,
            after.st_ino,
        ) or after.st_size < end["offset"]:
            raise fail("读取期间 JSONL 被替换或截断")
        if not commit and (before.st_size, before.st_mtime_ns) != (
            after.st_size,
            after.st_mtime_ns,
        ):
            raise fail("外部 snapshot 读取期间发生变化")
        if commit and offset == end["offset"] and sequence != end.get("sequence"):
            raise fail("JSONL 记录数量与提交边界不一致")
    return dict(
        records=rows,
        next_cursor=dict(
            generation=source["generation"], offset=offset, sequence=sequence
        ),
        snapshot_end=end,
        has_more=offset < end["offset"],
        status="ready",
    )
