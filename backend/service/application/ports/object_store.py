"""应用层持久对象存储端口。"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


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
