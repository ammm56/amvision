"""完整资产的真实发布/读取验收，显式隔离存储，不修改业务服务。"""

import argparse
from hashlib import sha256
import json
from pathlib import Path
import platform
from time import perf_counter

import numpy as np

from backend.contracts.workflows.workflow_graph import (
    WorkflowGraphTemplate,
    FlowApplication,
)
from backend.service.application.runtime.resource_scope import ResourceScope
from backend.service.application.workflows.documents.measurement_resources import (
    MeasurementResourceService,
)
from backend.service.application.workflows.point_cloud.runtime import get_cloud_runtime
from backend.service.application.workflows.point_cloud.detail_index import (
    read_index,
    read_block,
)
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
    DatasetStorageSettings,
)
from custom_nodes.metrology3d_nodes.shared.io.read_file import read_file_reference
from custom_nodes.metrology3d_nodes.shared.cloud_assets import save_cloud, read_asset
from tests.point_cloud_support import options
from tests.metrology3d_transport_support import cloud_documents
from tests.integration.metrology3d.capacity_support import settings
from tests.integration.metrology3d.published_support import published_system


def documents(reference):
    """真实保存资产 -> Read Cloud -> Cloud Preview；无新节点或假执行入口。"""
    template, app = cloud_documents()
    graph = template.model_dump(mode="json")
    graph["nodes"] = [
        dict(
            node_id="read",
            node_type_id="custom.metrology3d.read-cloud",
            parameters=dict(
                source=dict(kind="asset", reference=reference.model_dump(mode="json"))
            ),
        ),
        dict(
            node_id="preview",
            node_type_id="custom.metrology3d.cloud-preview",
            parameters=dict(
                point_limit=100000, color=dict(mode="solid"), prepare_details=True
            ),
        ),
    ]
    graph["edges"] = [
        dict(
            edge_id="display",
            source_node_id="read",
            source_port="cloud",
            target_node_id="preview",
            target_port="cloud",
        )
    ]
    graph["nodes"].append(
        dict(
            node_id="response",
            node_type_id="core.output.http-response",
            parameters=dict(status_code=200),
        )
    )
    graph["edges"].append(
        dict(
            edge_id="response",
            source_node_id="preview",
            source_port="body",
            target_node_id="response",
            target_port="body",
        )
    )
    graph["template_inputs"] = []
    graph["template_outputs"] = [
        dict(
            output_id="http_response",
            display_name="Cloud",
            payload_type_id="http-response.v1",
            source_node_id="response",
            source_port="response",
        )
    ]
    application = app.model_dump(mode="json")
    application["bindings"] = [
        dict(
            binding_id="http_response",
            direction="output",
            template_port_id="http_response",
            binding_kind="http-response",
        )
    ]
    return WorkflowGraphTemplate.model_validate(graph), FlowApplication.model_validate(
        application
    )


def save_sample(service, path, policy):
    """显式保存真实原云；解析后的数组仍按原精度逐行保存。"""
    with path.open("rb") as stream:
        metadata = service.storage.write_immutable_stream(
            object_prefix="projects/project-1/results/input",
            source_stream=stream,
            media_type="application/octet-stream",
            extension="ply",
        ).metadata
    file = dict(
        transport_kind="storage",
        storage_ref="object-store",
        object_key=metadata.object_key,
        file_name=path.name,
        media_type=metadata.media_type,
        content_length=metadata.content_length,
        checksum_algorithm="sha256",
        checksum=metadata.checksum,
        immutable_version=metadata.immutable_version,
    )
    scope = ResourceScope(kind="workflow")
    runtime = get_cloud_runtime(scope, run_id="detail-save", policy=policy.io)
    try:
        cloud = read_file_reference(
            runtime=runtime,
            object_store=service.storage,
            project_id="project-1",
            file=file,
            options=options(),
            cancel=lambda: None,
        )
        return save_cloud(
            runtime,
            cloud,
            service=service,
            project_id="project-1",
            name="Full workpiece",
            mode="derived",
            write_identity="a" * 64,
            policy=policy.assets(),
            cancel=lambda: None,
        )
    finally:
        assert not scope.close() and runtime.budget.used == 0


def verify(service, reference, policy):
    """所有叶块按逻辑行回查原始 XYZ，验证不丢行、不重行、不改变原始行号。"""
    index = read_index(
        service, reference, project_id="project-1", policy=policy.preview
    )
    scope = ResourceScope(kind="workflow")
    runtime = get_cloud_runtime(scope, run_id="detail-verify", policy=policy.io)
    seen = np.zeros(index.point_count, dtype=bool)
    try:
        cloud = read_asset(
            runtime,
            reference,
            service=service,
            project_id="project-1",
            policy=policy.assets(),
            cancel=lambda: None,
        )
        with runtime.borrow(cloud) as view:
            for block in index.blocks:
                raw = read_block(
                    service,
                    reference,
                    block.block_id,
                    generation=index.generation,
                    project_id="project-1",
                    policy=policy.preview,
                )
                rows = np.ndarray(
                    (block.count,),
                    dtype="<u8",
                    buffer=raw,
                    offset=index.logical_offset,
                    strides=(index.row_bytes,),
                )
                identity = np.ndarray(
                    (block.count,),
                    dtype="<u8",
                    buffer=raw,
                    offset=index.identity_offset,
                    strides=(index.row_bytes,),
                )
                assert not seen[rows].any() and len(np.unique(rows)) == len(rows)
                seen[rows] = True
                values, expected = view.gather(rows)
                np.testing.assert_array_equal(identity, expected)
                for field in index.fields:
                    actual = np.ndarray(
                        (block.count, field.components),
                        dtype=np.dtype(field.dtype).newbyteorder("<"),
                        buffer=raw,
                        offset=field.offset,
                        strides=(index.row_bytes, np.dtype(field.dtype).itemsize),
                    )
                    np.testing.assert_array_equal(actual, values[field.name])
        assert int(seen.sum()) == index.valid_count
        return dict(
            point_count=index.point_count,
            valid_count=index.valid_count,
            excluded_count=index.excluded_count,
            block_count=len(index.blocks),
            data_bytes=sum(b.byte_length for b in index.blocks),
            bounds=index.bounds.model_dump(),
            all_rows_fields_exact=True,
        )
    finally:
        assert not scope.close() and runtime.budget.used == 0


def main():
    """可选启动同一验收 API，结束后停止所有本轮进程。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--sample", type=Path, required=True)
    parser.add_argument("--serve", type=int)
    args = parser.parse_args()
    if args.serve is not None and (
        args.serve in (5600, 5601) or not 1024 <= args.serve <= 65535
    ):
        parser.error("必须使用隔离端口")
    args.root.mkdir(parents=True, exist_ok=False)
    config = settings()
    policy = config.workflow_runtime.point_cloud
    with published_system(args.root / "system", point_cloud_policy=policy) as system:
        service = MeasurementResourceService(
            LocalDatasetStorage(
                DatasetStorageSettings(
                    root_dir=system.settings.dataset_storage.root_dir
                )
            )
        )
        reference = save_sample(service, args.sample, policy)
        version = system.publish(point_limit=100000, documents=documents(reference))
        system.start(version)
        started = perf_counter()
        response = system.call(
            "POST",
            f"/app-runtimes/{system.runtime_id}/invoke",
            json=dict(input_bindings={}, execution_metadata={}),
        )
        (args.root / "response.json").write_text(
            json.dumps(response, ensure_ascii=False), encoding="utf-8"
        )
        elapsed = perf_counter() - started
        summary = verify(service, reference, policy)
        url = f"/projects/project-1/measurement-resources/{reference.resource_id}/versions/{reference.version}/details"
        index_response = system.client.get(
            system.base + url,
            params=dict(sha256=reference.sha256),
            headers=system.headers,
        )
        assert index_response.status_code == 200
        assert index_response.headers["cache-control"] == "no-store"
        index = index_response.json()
        first = system.client.get(
            system.base + url + "/0",
            params=dict(sha256=reference.sha256, generation=index["generation"]),
            headers=system.headers,
        )
        assert (
            first.status_code == 200
            and first.headers["cache-control"] == "no-store"
            and sha256(first.content).hexdigest() == index["blocks"][0]["sha256"]
        )
        invalid = system.client.get(
            system.base + url + "/0",
            params=dict(sha256=reference.sha256, generation="0" * 32),
            headers=system.headers,
        )
        assert invalid.status_code == 400
        summary.update(
            platform=platform.platform(),
            published_version=version,
            runtime_id=system.runtime_id,
            prepare_seconds=elapsed,
            api_exact=True,
            stale_generation_rejected=True,
            uncached_responses=True,
        )
        (args.root / "report.json").write_text(
            json.dumps(summary, indent=2), encoding="utf-8"
        )
        print(json.dumps(summary), flush=True)
        if args.serve:
            import uvicorn

            uvicorn.run(
                system.client.app, host="127.0.0.1", port=args.serve, lifespan="off"
            )


if __name__ == "__main__":
    main()
