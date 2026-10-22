"""交换文件沿既有 ObjectStore 发布，临时编码文件不成为长期资产。"""

from tempfile import TemporaryFile
from backend.nodes.core_nodes.support.file_payloads import require_file_ref_payload
from backend.nodes.core_nodes.support.logic import build_value_payload
from custom_nodes._metrology3d_nodes.shared.io.export_file import (
    export_cloud_file,
    CloudExportOptions,
)
from custom_nodes._metrology3d_nodes.shared.node_runtime import write_identity


def publish_export(request, env, cloud, parameters):
    """编码与存储都检查取消；已提交产物不因迟到取消被删除。"""
    storage = env.service.storage
    identity = write_identity(request, env.project_id)
    options = CloudExportOptions.model_validate(
        parameters.model_dump(exclude={"source"})
    )
    # 临时文件位于配置的运行数据盘；强杀由 OS 关闭句柄，不遗留命名半文件。
    storage.root_dir.mkdir(parents=True, exist_ok=True)
    with TemporaryFile(mode="w+b", dir=storage.root_dir) as stream:
        summary, _ = export_cloud_file(
            env.runtime,
            cloud,
            options,
            stream=stream,
            max_output_bytes=env.policy.max_export_bytes,
            cancel=env.cancel,
        )
        stream.seek(0)

        class CancelledRead:
            """存储复制过程中仍响应本节点已有取消控制。"""

            def read(self, size):
                env.cancel()
                return stream.read(size)

        receipt = storage.write_immutable_stream(
            object_prefix=f"projects/{env.project_id}/workflow-exports/{identity}",
            source_stream=CancelledRead(),
            media_type="application/octet-stream",
            extension=".bin",
            chunk_size=env.policy.io.chunk_bytes,
            max_bytes=env.policy.max_export_bytes,
        )
    meta = receipt.metadata
    file = require_file_ref_payload(
        dict(
            transport_kind="storage",
            storage_ref="object-store",
            object_key=meta.object_key,
            file_name=options.file_name,
            media_type=meta.media_type,
            content_length=meta.content_length,
            checksum_algorithm="sha256",
            checksum=meta.checksum,
            immutable_version=meta.immutable_version,
        )
    )
    summary["file_checksum"] = meta.checksum
    return {"file": file, "summary": build_value_payload(summary)}
