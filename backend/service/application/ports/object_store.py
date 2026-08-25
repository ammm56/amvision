"""应用层持久对象存储端口。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import BinaryIO, ContextManager, Protocol, runtime_checkable


@dataclass(frozen=True)
class ObjectSnapshotMetadata:
    """描述一次可验证对象快照的稳定元数据。"""

    object_key: str
    content_length: int
    media_type: str
    checksum_algorithm: str | None = None
    checksum: str | None = None
    immutable_version: str | None = None
    is_immutable: bool = False


@dataclass(frozen=True)
class ObjectReadSnapshot:
    """保存只读对象 handle 及其同一版本元数据。"""

    stream: BinaryIO
    metadata: ObjectSnapshotMetadata


@dataclass(frozen=True)
class ObjectWriteReceipt:
    """描述不可变对象原子发布结果。"""

    metadata: ObjectSnapshotMetadata


@runtime_checkable
class ObjectStore(Protocol):
    """以 POSIX 风格相对 object key 管理持久对象。

    该端口只描述应用层需要的对象操作，不暴露存储根目录或本机绝对路径。
    """

    def prepare_prefix(self, object_prefix: str) -> None:
        """准备对象前缀。

        参数：
        - object_prefix：POSIX 风格相对对象前缀。

        不需要显式目录的实现可以把该操作作为 no-op。
        """

        ...

    def write_bytes(self, object_key: str, content: bytes) -> None:
        """把二进制内容写入指定 object key。

        参数：
        - object_key：目标对象的相对 key。
        - content：完整二进制内容。
        """

        ...

    def write_text(self, object_key: str, content: str) -> None:
        """把文本内容写入指定 object key。

        参数：
        - object_key：目标对象的相对 key。
        - content：完整文本内容。
        """

        ...

    def write_json(self, object_key: str, payload: object) -> None:
        """把 JSON 可序列化内容写入指定 object key。

        参数：
        - object_key：目标对象的相对 key。
        - payload：JSON 可序列化内容。
        """

        ...

    def copy_object(self, source_object_key: str, destination_object_key: str) -> None:
        """在 ObjectStore 内复制对象。

        参数：
        - source_object_key：源对象的相对 key。
        - destination_object_key：目标对象的相对 key。
        """

        ...

    def stat_object(self, object_key: str) -> ObjectSnapshotMetadata:
        """读取对象长度和已发布的不可变 identity，不重复扫描大对象。"""

        ...

    def open_read_snapshot(
        self,
        object_key: str,
        *,
        expected_version: str | None = None,
        expected_checksum: str | None = None,
    ) -> ContextManager[ObjectReadSnapshot]:
        """打开在 context 生命周期内保持同一内容的只读快照。"""

        ...

    def write_immutable_object(
        self,
        *,
        object_prefix: str,
        content: bytes,
        media_type: str,
        extension: str | None = None,
    ) -> ObjectWriteReceipt:
        """按 content address 原子发布不可变对象。"""

        ...

    def materialize_immutable_object(
        self,
        *,
        source_object_key: str,
        object_prefix: str,
        media_type: str | None = None,
    ) -> ObjectWriteReceipt:
        """把可变或旧对象物化为新的不可变受管理对象。"""

        ...
