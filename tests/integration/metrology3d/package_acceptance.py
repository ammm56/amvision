"""完整工件在两个空存储间搬运，沿真实 API 发布和 Runtime 执行。"""

import argparse
from hashlib import sha256
import json
from pathlib import Path
import platform
from threading import Event, Thread

from backend.contracts.workflows.metrology import ResourceReference
from backend.service.application.workflows.documents.measurement_resources import (
    MeasurementResourceService,
)
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
    DatasetStorageSettings,
)
from tests.integration.metrology3d.capacity_support import settings
from tests.integration.metrology3d.detail_acceptance import documents, save_sample
from tests.integration.metrology3d.published_support import published_system


def serve(system, root, port):
    """仅限隔离端口；停止文件使服务正常退出并清理 Runtime/Broker。"""
    import uvicorn

    server = uvicorn.Server(
        uvicorn.Config(system.client.app, host="127.0.0.1", port=port, lifespan="off")
    )
    finished = Event()

    def stop():
        while not finished.wait(0.2):
            if (root / "stop").exists():
                server.should_exit = True
                return

    monitor = Thread(target=stop, daemon=True)
    monitor.start()
    try:
        server.run()
    finally:
        finished.set()
        monitor.join()


def main():
    """完整样本只解析一次，不重复测量性能或构建显示索引。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--sample", type=Path)
    parser.add_argument("--package", type=Path)
    parser.add_argument("--serve", type=int)
    args = parser.parse_args()
    if bool(args.sample) == bool(args.package):
        parser.error("sample/package 必须二选一")
    if args.serve and (args.serve in (5600, 5601) or not 1024 <= args.serve <= 65535):
        parser.error("必须使用隔离端口")
    root = args.root.resolve()
    root.mkdir(parents=True, exist_ok=False)
    policy = settings().workflow_runtime.point_cloud
    if args.sample:
        (root / "source").mkdir()
        with published_system(root / "source", point_cloud_policy=policy) as source:
            resources = MeasurementResourceService(
                LocalDatasetStorage(
                    DatasetStorageSettings(
                        root_dir=source.settings.dataset_storage.root_dir
                    )
                )
            )
            ref = save_sample(resources, args.sample, policy)
            graph, app = documents(ref)
            for node in graph.nodes:
                if node.node_type_id == "custom.metrology3d.cloud-preview":
                    node.parameters["prepare_details"] = False
            response = source.client.post(
                source.base + "/projects/project-1/application-packages/export",
                headers=source.headers,
                json=dict(
                    format_id="amvision.workflow-app-document.v1",
                    application=app.model_dump(mode="json"),
                    template=graph.model_dump(mode="json"),
                ),
            )
            assert response.status_code == 200, response.text[:2000]
            payload = response.content
            (root / "workpiece.zip").write_bytes(payload)
    else:
        payload = args.package.read_bytes()
    (root / "target").mkdir()
    with published_system(root / "target", point_cloud_policy=policy) as target:
        base = "/projects/project-1"
        assert target.call("GET", base + "/measurement-resources") == []
        response = target.client.post(
            target.base + base + "/application-packages/import",
            content=payload,
            headers={
                **target.headers,
                "Content-Type": "application/zip",
                "Idempotency-Key": "full-sample",
            },
        )
        assert response.status_code == 201, response.text[:2000]
        result = response.json()
        app_path = base + "/applications/" + result["application_id"]
        draft = target.call("GET", app_path)
        version = target.call(
            "POST",
            app_path + "/versions",
            status=201,
            json=dict(
                expected_draft_fingerprint=draft["draft_fingerprint"],
                release_notes="A10 empty target import",
            ),
        )["workflow_app_version_id"]
        target.start(version)
        run = target.call(
            "POST",
            f"/app-runtimes/{target.runtime_id}/invoke",
            json=dict(input_bindings={}, execution_metadata={}),
        )
        assert run["state"] == "succeeded", run
        resources = MeasurementResourceService(
            LocalDatasetStorage(
                DatasetStorageSettings(
                    root_dir=target.settings.dataset_storage.root_dir
                )
            )
        )
        mapped = ResourceReference.model_validate(
            result["resource_mapping"][0]["target"]
        )
        original = ResourceReference.model_validate(
            result["resource_mapping"][0]["source"]
        )
        asset = resources.read(mapped, project_id="project-1")
        assert mapped.sha256 == original.sha256
        assert asset.content.point_cloud.point_count == 14745099
        report = dict(
            platform=platform.platform(),
            archive_bytes=len(payload),
            archive_sha256=sha256(payload).hexdigest(),
            point_count=asset.content.point_cloud.point_count,
            preserved_content_sha256=mapped.sha256,
            empty_target=True,
            app_id=result["application_id"],
            version=version,
            runtime_id=target.runtime_id,
            run_state=run["state"],
            source_required_after_import=False,
        )
        (root / "report.json").write_text(
            json.dumps(report, indent=2), encoding="utf-8"
        )
        (root / "response.json").write_text(json.dumps(run), encoding="utf-8")
        print(json.dumps(report), flush=True)
        if args.serve:
            serve(target, root, args.serve)


if __name__ == "__main__":
    main()
