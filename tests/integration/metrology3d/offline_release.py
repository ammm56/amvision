"""真实 CPU 发行验收：隔离环境、正式启动器、HTTP、完整工件与停止恢复。"""

import argparse
from hashlib import file_digest
import json
import os
from pathlib import Path
import re
import subprocess
from time import monotonic, sleep
from types import SimpleNamespace

import httpx
import psutil

from tests.integration.release_environment import build_release_test_environment


REPOSITORY = Path(__file__).resolve().parents[3]


def prepare(sample: Path, root: Path) -> None:
    """仅在构建机将正式完整配方与原云保存打包；不创建运行时或替代准入。"""
    from backend.contracts.workflows.cloud_package import WorkflowAppDocument
    from backend.nodes.local_node_pack_loader import LocalNodePackLoader
    from backend.nodes.node_catalog_registry import NodeCatalogRegistry
    from backend.service.application.workflows.cloud_package import export_cloud_package
    from backend.service.application.workflows.documents.measurement_resources import (
        MeasurementResourceService,
    )
    from backend.service.application.workflows.point_cloud.execution_policy import (
        PointCloudExecutionPolicy,
    )
    from backend.service.application.workflows.workflow_service import (
        LocalWorkflowJsonService,
    )
    from backend.service.infrastructure.object_store.local_dataset_storage import (
        LocalDatasetStorage,
        DatasetStorageSettings,
    )
    from scripts.metrology_workpiece import build_documents
    from tests.integration.metrology3d.detail_acceptance import save_sample

    root.mkdir(parents=True, exist_ok=False)
    config = json.loads(
        (
            REPOSITORY / "custom_nodes/metrology3d_nodes/workstation.example.json"
        ).read_text("utf-8")
    )
    policy = PointCloudExecutionPolicy.model_validate(
        config["workflow_runtime"]["point_cloud"]
    )
    storage = LocalDatasetStorage(DatasetStorageSettings(root_dir=root / "source"))
    resource = save_sample(MeasurementResourceService(storage), sample, policy)
    graph, app = build_documents(view="full")
    graph, app = graph.model_dump(mode="json"), app.model_dump(mode="json")
    next(n for n in graph["nodes"] if n["node_id"] == "read")["parameters"] = dict(
        source=dict(kind="asset", reference=resource.model_dump(mode="json"))
    )
    graph["template_inputs"] = []
    app["bindings"] = [b for b in app["bindings"] if b["direction"] != "input"]
    # 原显示支路保留；不在发行验收重复创建近 1 GB 显示索引。
    for node in graph["nodes"]:
        if node["node_type_id"] == "custom.metrology3d.cloud-preview":
            node["parameters"]["prepare_details"] = False
    loader = LocalNodePackLoader(REPOSITORY / "custom_nodes")
    loader.refresh()
    service = LocalWorkflowJsonService(
        dataset_storage=storage,
        node_catalog_registry=NodeCatalogRegistry(node_pack_loader=loader),
        point_cloud_policy=policy,
    )
    document = WorkflowAppDocument(
        format_id="amvision.workflow-app-document.v1", template=graph, application=app
    )
    with (root / "workpiece.zip").open("wb") as output:
        export_cloud_package(
            service,
            document,
            project_id="project-1",
            stream=output,
            policy=policy.assets(),
            cancel=lambda: None,
        )
    print(
        json.dumps(
            dict(
                package=str(root / "workpiece.zip"),
                nodes=len(graph["nodes"]),
                resource=resource.model_dump(mode="json"),
            )
        ),
        flush=True,
    )


def wait_until(predicate, *, timeout=180):
    """只等待服务控制状态，不改变生产调用准入或新增请求等待队列。"""
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        if predicate():
            return
        sleep(0.25)
    raise TimeoutError("发行验收控制状态未就绪")


def exercise(root: Path, package: Path, report_dir: Path, port: int) -> None:
    """对实际发行进程做两次启动，中间停止整组，不使用 TestClient 或测试节点。"""
    from tests.integration.metrology3d.workpiece_workflow import check_record

    if port in (5600, 5601, 5620, 5621):
        raise ValueError("必须使用独立发行端口")
    report_dir.mkdir(parents=True, exist_ok=False)
    python = root / ("python/python.exe" if os.name == "nt" else "python/bin/python3")
    environment = build_release_test_environment(root)
    environment.update(
        HF_HUB_OFFLINE="1",
        TRANSFORMERS_OFFLINE="1",
        HTTP_PROXY="http://127.0.0.1:9",
        HTTPS_PROXY="http://127.0.0.1:9",
        NO_PROXY="127.0.0.1,localhost",
    )
    validation = subprocess.run(
        [
            str(python),
            "-I",
            str(root / "launchers/maintenance/invoke_backend_maintenance.py"),
            "--app-root",
            str(root),
            "--",
            "validate-layout",
        ],
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=180,
    )
    (report_dir / "validate-layout.log").write_text(
        validation.stdout + validation.stderr, encoding="utf-8"
    )
    assert validation.returncode == 0, validation.stdout + validation.stderr
    report = dict(platform=os.name, release=str(root), cycles=[], validate_layout=True)
    with package.open("rb") as stream:
        report["package_sha256"] = file_digest(stream, "sha256").hexdigest()
    client = httpx.Client(
        base_url=f"http://127.0.0.1:{port}", timeout=240, trust_env=False
    )
    runtime_id = version = app_id = None
    identities = []

    def call(method, path, *, status=200, **kwargs):
        response = client.request(method, "/api/v1" + path, **kwargs)
        assert response.status_code == status, (
            path,
            response.status_code,
            response.text[:8000],
        )
        return response.json() if response.content else None

    for cycle in range(2):
        with (report_dir / f"launcher-{cycle}.log").open("wb") as log:
            process = subprocess.Popen(
                [
                    str(python),
                    "-I",
                    str(root / "start_amvision_full.py"),
                    "--app-root",
                    str(root),
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(port),
                ],
                cwd=root,
                env=environment,
                stdout=log,
                stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            try:

                def ready():
                    assert process.poll() is None, (
                        "full supervisor 提前退出，请检查日志"
                    )
                    try:
                        state = json.loads(
                            (root / "logs/full-stack/launcher-status.json").read_text(
                                "utf-8"
                            )
                        )
                        return state.get("state") == "running"
                    except (FileNotFoundError, json.JSONDecodeError):
                        return False

                wait_until(ready, timeout=360)
                login = call(
                    "POST",
                    "/auth/login",
                    json=dict(username="amvar", password="123456"),
                )
                client.headers["Authorization"] = "Bearer " + login["access_token"]
                html = client.get("/")
                assert html.status_code == 200 and '<div id="app">' in html.text
                assets = re.findall(r'(?:src|href)="(/assets/[^\"]+)"', html.text)
                assert assets
                for asset in assets:
                    assert client.get(asset).status_code == 200
                if cycle == 0:
                    call(
                        "POST",
                        "/projects/bootstrap",
                        status=201,
                        json=dict(
                            project_id="project-1", display_name="CPU offline workpiece"
                        ),
                    )
                    assert (
                        call(
                            "GET", "/workflows/projects/project-1/measurement-resources"
                        )
                        == []
                    )
                    with package.open("rb") as stream:
                        imported = call(
                            "POST",
                            "/workflows/projects/project-1/application-packages/import",
                            status=201,
                            content=stream,
                            headers={
                                "Content-Type": "application/zip",
                                "Idempotency-Key": "a12-empty-target",
                            },
                        )
                    app_id = imported["application_id"]
                    path = "/workflows/projects/project-1/applications/" + app_id
                    draft = call("GET", path)
                    version = call(
                        "POST",
                        path + "/versions",
                        status=201,
                        json=dict(
                            expected_draft_fingerprint=draft["draft_fingerprint"],
                            release_notes="A12 full offline release acceptance",
                        ),
                    )["workflow_app_version_id"]
                    runtime_id = call(
                        "POST",
                        "/workflows/app-runtimes",
                        status=201,
                        json=dict(
                            project_id="project-1",
                            workflow_app_version_id=version,
                            display_name="A12 full workpiece",
                            request_timeout_seconds=180,
                        ),
                    )["workflow_runtime_id"]
                    report.update(
                        application_id=app_id,
                        version=version,
                        runtime_id=runtime_id,
                        resource_mapping=imported["resource_mapping"],
                    )
                call("POST", f"/workflows/app-runtimes/{runtime_id}/start")
                started = monotonic()
                run = call(
                    "POST",
                    f"/workflows/app-runtimes/{runtime_id}/invoke",
                    json=dict(input_bindings={}, execution_metadata={}),
                )
                assert run["state"] == "succeeded", run
                system = SimpleNamespace(
                    settings=SimpleNamespace(
                        dataset_storage=SimpleNamespace(root_dir=root / "data/files")
                    )
                )
                record = check_record(run["results"]["body"], system)
                (report_dir / f"run-{cycle}.json").write_text(
                    json.dumps(run, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                report["cycles"].append(
                    dict(
                        cycle=cycle,
                        state=run["state"],
                        item_count=len(record["metrics"]["items"]),
                        elapsed_seconds=monotonic() - started,
                        static_assets=len(assets),
                    )
                )
                call("POST", f"/workflows/app-runtimes/{runtime_id}/stop")
                identities = [
                    (p.pid, p.create_time())
                    for p in psutil.Process(process.pid).children(recursive=True)
                ]
            finally:
                stopped = subprocess.run(
                    [
                        str(python),
                        "-I",
                        str(root / "stop_amvision_full.py"),
                        "--app-root",
                        str(root),
                    ],
                    cwd=root,
                    env=environment,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    timeout=180,
                )
                (report_dir / f"stop-{cycle}.log").write_text(
                    stopped.stdout + stopped.stderr, encoding="utf-8"
                )
                process.wait(timeout=180)
                assert stopped.returncode == 0, stopped.stdout + stopped.stderr

                def all_exited():
                    for pid, created in identities:
                        try:
                            item = psutil.Process(pid)
                            if (
                                item.create_time() == created
                                and item.status() != psutil.STATUS_ZOMBIE
                            ):
                                return False
                        except psutil.NoSuchProcess:
                            pass
                    return True

                wait_until(all_exited, timeout=30)
    client.close()
    report["whole_group_stopped"] = True
    (report_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False), flush=True)


def main():
    """显式选择准备包或真实发行验收，避免日常 pytest 自动启动服务。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare", type=Path)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--package", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--port", type=int)
    args = parser.parse_args()
    if args.prepare:
        prepare(args.prepare, args.root.resolve())
    else:
        exercise(
            args.root.resolve(),
            args.package.resolve(),
            args.report.resolve(),
            args.port,
        )


if __name__ == "__main__":
    main()
