"""三维文件共享现有不可变快照准入，不重复建立文件或缓存系统。"""

from contextlib import contextmanager
from hashlib import sha256

from backend.contracts.workflows.point_cloud import MAX_POINT_CLOUD_INPUT_BYTES
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.input_contracts import WorkflowInputValidator


@contextmanager
def checked_input_snapshot(*, object_store, project_id, file, policy, cancel):
    """权限、不可变版本与实际字节校验完成后，将同一快照交给解码器。"""
    cancel()
    payload = WorkflowInputValidator(object_store=object_store).validate_file_reference(
        payload=file,
        project_id=project_id,
        max_file_bytes=MAX_POINT_CLOUD_INPUT_BYTES,
        binding_id="file",
    )
    if payload["content_length"] == 0:
        raise InvalidRequestError("点云输入文件不能为空")
    with object_store.open_read_snapshot(
        str(payload["object_key"]),
        expected_version=str(payload["immutable_version"]),
        expected_checksum=str(payload["checksum"]),
    ) as snapshot:
        if (
            not snapshot.metadata.is_immutable
            or snapshot.metadata.content_length != payload["content_length"]
        ):
            raise InvalidRequestError("点云输入不是声明的不可变快照")
        digest, length = sha256(), 0
        while True:
            cancel()
            block = snapshot.stream.read(policy.chunk_bytes)
            if not block:
                break
            length += len(block)
            if length > int(payload["content_length"]):
                raise InvalidRequestError("点云快照实际长度超过声明")
            digest.update(block)
        del block
        if (
            length != payload["content_length"]
            or digest.hexdigest() != payload["checksum"]
        ):
            raise InvalidRequestError("点云快照实际字节与摘要不一致")
        snapshot.stream.seek(0)
        yield payload, snapshot.stream
