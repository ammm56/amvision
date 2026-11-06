"""B06 真实发布、独立 Runtime 与正式 Python/.NET 调用；不替换准入。"""

from concurrent.futures import CancelledError
import json
import os
import subprocess
import sys

import numpy as np
import pytest

from backend.contracts.workflows.workflow_graph import (
    WorkflowGraphTemplate,
    FlowApplication,
)
from runtimes.clients.point_cloud import PointCloudClient, PointCloudCallError
from tests.metrology3d_transport_support import cloud_documents
from tests.integration.metrology3d.published_support import published_system
from tests.integration.metrology3d.test_published_runtime import PROBE
from tests.test_metrology3d_raster_buffer import descriptor, payload
from tests.test_metrology3d_preview import decode
from tests.test_metrology3d_raster_conversion import specification
from tests.test_metrology3d_raster_io import encode
from tests.integration.metrology3d.published_client import wait_for


def saved_raster_documents(*, reference=None, spec=None, save=True):
    """正式保存后以固定资产重新发布，不在 worker 内伪造运行引用。"""
    from tests.point_cloud_support import options

    template, app = (
        raster_documents(spec=spec)
        if reference is None
        else cloud_documents(options().model_dump(mode="json"))
    )
    graph, application = template.model_dump(mode="json"), app.model_dump(mode="json")
    if reference is not None:
        graph["nodes"][0]["parameters"] = {
            "source": {"kind": "asset", "reference": reference}
        }
        graph["template_inputs"] = []
        application["bindings"] = [
            b for b in application["bindings"] if b["direction"] == "output"
        ]
    if save:
        graph["nodes"].append(
            dict(
                node_id="save",
                node_type_id="custom.metrology3d.save-cloud",
                parameters=dict(
                    mode="original" if reference is None else "derived",
                    target=dict(kind="new", name="Raster source"),
                ),
            )
        )
        graph["edges"].append(
            dict(
                edge_id="save-raster",
                source_node_id="raster" if reference is None else "filter",
                source_port="cloud",
                target_node_id="save",
                target_port="cloud",
            )
        )
    return WorkflowGraphTemplate.model_validate(graph), FlowApplication.model_validate(
        application
    )


def publish_saved_raster_roundtrip(system, spec, content):
    """三代真实发布/调用：保存原件、重读派生保存、重读再次派生保存及最终显示。"""
    seen = set()
    reference = None
    for generation in range(1, 5):
        version = system.publish(
            documents=saved_raster_documents(
                reference=reference, spec=spec, save=generation < 4
            )
        )
        if generation > 1:
            system.call("POST", f"/app-runtimes/{system.runtime_id}/stop")
            if generation == 2:
                # 文件入口改为固定资产属于公开输入删除，不能绕过切版保护。
                rejected = system.call(
                    "POST",
                    f"/app-runtimes/{system.runtime_id}/select-version",
                    status=409,
                    json={
                        "workflow_app_version_id": version,
                        "expected_generation": 1,
                    },
                )
                assert rejected["error"]["code"] == "resource_conflict"
                system.runtime_id = None
            else:
                system.call(
                    "POST",
                    f"/app-runtimes/{system.runtime_id}/select-version",
                    json={
                        "workflow_app_version_id": version,
                        "expected_generation": generation - 2,
                    },
                )
        system.start(version if generation <= 2 else None)
        if generation == 1:
            reply = system.call(
                "POST",
                f"/app-runtimes/{system.runtime_id}/invoke/upload",
                files={
                    "cloud": ("calibrated.npy", content, "application/octet-stream"),
                },
            )
        else:
            reply = system.call(
                "POST",
                f"/app-runtimes/{system.runtime_id}/invoke",
                json={"input_bindings": {}, "execution_metadata": {}},
            )
        assert reply["state"] == "succeeded", reply
        body = reply["results"]["body"]
        assert body["source_point_count"] == spec.point_count()
        assert body["raster_source"]["calibration_id"] == spec.calibration_id
        system.assert_reclaimed()
        resources = system.call("GET", "/projects/project-1/measurement-resources")
        assert len(resources) == min(generation, 3)
        if generation < 4:
            reference = next(
                r["reference"]
                for r in resources
                if r["reference"]["resource_id"] not in seen
            )
            seen.add(reference["resource_id"])
    return body


def test_raster_real_publish_repeated_asset_derivation(tmp_path):
    """保存链路跨独立 worker 和发布版本仍有完整标定；停止后许可归零。"""
    spec = specification()
    raw = np.arange(12, dtype="f4").reshape(3, 4)
    with published_system(tmp_path) as system:
        body = publish_saved_raster_roundtrip(system, spec, encode(raw, "npy"))
        arrays = decode(body)
        ids = np.arange(1, 12)
        np.testing.assert_array_equal(arrays["source_indices"][:, 0], ids)
        np.testing.assert_allclose(
            arrays["positions"],
            np.column_stack(((ids % 4 - 1) * ids / 2, (ids // 4 - 1) * ids / 3, ids)),
            atol=2e-6,
        )
        system.call("POST", f"/app-runtimes/{system.runtime_id}/stop")
        system.assert_reclaimed()


def raster_documents(*, spec=None, file_format="npy"):
    """文件或同机数组只切换入口，其余使用真实 Filter Valid / Cloud Preview。"""
    template, app = cloud_documents()
    graph = template.model_dump(mode="json")
    graph["nodes"].insert(
        0,
        dict(
            node_id="raster",
            node_type_id="custom.metrology3d.raster-to-cloud",
            parameters={
                "settings": {"kind": "local-array"}
                if spec is None
                else {
                    "kind": "file",
                    "file_format": file_format,
                    "raster": spec.model_dump(mode="json"),
                }
            },
        ),
    )
    graph["template_inputs"][0].update(
        payload_type_id="calibrated-raster.v1" if spec is None else "file-ref.v1",
        target_node_id="raster",
        target_port="raster" if spec is None else "file",
    )
    graph["edges"].append(
        dict(
            edge_id="raster-filter",
            source_node_id="raster",
            source_port="cloud",
            target_node_id="filter",
            target_port="cloud",
        )
    )
    application = app.model_dump(mode="json")
    if spec is not None:
        application["bindings"][0]["config"] = {
            "allowed_media_types": ["application/octet-stream"],
            "max_file_bytes": 1_000_000_000,
        }
    return WorkflowGraphTemplate.model_validate(graph), FlowApplication.model_validate(
        application
    )


def check_body(body):
    """按解析式独立核对坐标和像素行号，不能以预览成功代替几何检查。"""
    assert body["point_count"] == 10 and body["source_point_count"] == 12
    assert body["raster_source"]["calibration_id"] == "test-camera"
    arrays = decode(body)
    ids = arrays["source_indices"][:, 0]
    np.testing.assert_array_equal(ids, np.arange(2, 12))
    expected = np.array(
        [[(i % 4 - 1) * i / 2, (i // 4 - 1) * i / 3, i] for i in range(2, 12)]
    )
    positions = arrays["positions"]
    np.testing.assert_allclose(positions, expected, atol=2e-6)


def test_raster_real_publish_python_lifecycle(tmp_path):
    with published_system(tmp_path) as system:
        version = system.publish(documents=raster_documents())
        runtime = system.start(version)
        generation = system.enable_source(create=True)
        client = PointCloudClient(
            buffers_root=system.settings.local_memory.root_dir,
            broker_settings=system.settings.local_buffer_broker,
        )
        kwargs = dict(
            source_id=system.source_id,
            generation=generation,
            raster=descriptor(),
            content=payload(),
            timeout_ms=30000,
            payload_key="cloud",
        )
        reply = client.invoke_raster(**kwargs)
        assert reply["state"] == "succeeded", reply
        check_body(reply["response_payload"]["results"]["body"])
        run = system.call("GET", f"/runs/{reply['workflow_run_id']}?response_mode=run")
        assert run["workflow_app_version_id"] == version
        assert run["worker_instance_id"] == runtime["worker_instance_id"]
        system.assert_reclaimed()
        calls = 0

        def cancel():
            nonlocal calls
            calls += 1
            return calls >= 2

        with pytest.raises(CancelledError):
            client.invoke_raster(**kwargs, cancelled=cancel)
        system.assert_reclaimed()
        with pytest.raises(PointCloudCallError):
            client.invoke_raster(**{**kwargs, "generation": generation + 1})
        system.assert_reclaimed()
        version2 = system.publish(point_limit=500, documents=raster_documents())
        system.call("POST", f"/app-runtimes/{system.runtime_id}/stop")
        system.call("POST", f"/trigger-sources/{system.source_id}/disable")
        selected = system.call(
            "POST",
            f"/app-runtimes/{system.runtime_id}/select-version",
            json={"workflow_app_version_id": version2, "expected_generation": 1},
        )
        assert selected["revision_generation"] == 2
        system.start()
        generation = system.enable_source()
        check_body(
            client.invoke_raster(**{**kwargs, "generation": generation})[
                "response_payload"
            ]["results"]["body"]
        )
        system.assert_reclaimed()


@pytest.mark.parametrize(
    "kind,dtype", [("npy", "float64"), ("png", "uint16"), ("tiff", "float32")]
)
def test_raster_published_file_upload_and_bad_input(tmp_path, kind, dtype):
    spec = specification(dtype=dtype)
    data = np.arange(12, dtype=dtype).reshape(3, 4)
    content = encode(data, kind)
    with published_system(tmp_path) as system:
        system.start(
            system.publish(documents=raster_documents(spec=spec, file_format=kind))
        )
        for value, expected in [(content[:12], "failed"), (content, "succeeded")]:
            response = system.call(
                "POST",
                f"/app-runtimes/{system.runtime_id}/invoke/upload",
                files={"cloud": (f"grid.{kind}", value, "application/octet-stream")},
            )
            assert response["state"] == expected, response
            if expected == "succeeded":
                body = response["results"]["body"]
                assert body["source_point_count"] == 12 and body["point_count"] == 11
                values = decode(body)
                np.testing.assert_array_equal(
                    values["source_indices"][:, 0], np.arange(1, 12)
                )
                np.testing.assert_allclose(
                    values["positions"],
                    [
                        [(i % 4 - 1) * i / 2, (i // 4 - 1) * i / 3, i]
                        for i in range(1, 12)
                    ],
                    atol=2e-6,
                )
            system.assert_reclaimed()


def test_raster_published_writer_crash_recovers(tmp_path):
    desc = tmp_path / "raster.json"
    data = tmp_path / "raster.bin"
    ready = tmp_path / "writer-ready"
    desc.write_text(descriptor().model_dump_json(), encoding="utf-8")
    data.write_bytes(payload())
    with published_system(tmp_path) as system:
        system.start(system.publish(documents=raster_documents()))
        generation = system.enable_source(create=True)
        args = [
            system.settings.local_memory.root_dir,
            system.source_id,
            str(generation),
            str(desc),
            str(data),
            "hold-writer",
            "5000",
            str(ready),
        ]
        command = (
            [str(PROBE), "--invoke-shared-memory-raster", *args]
            if os.name == "nt"
            else [
                sys.executable,
                "-m",
                "tests.integration.metrology3d.published_client",
                *args,
            ]
        )
        process = subprocess.Popen(
            command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        try:
            wait_for(ready.exists)
            assert system.idle()[1]["active_lease_count"] > 0
        finally:
            if process.poll() is None:
                process.kill()
            process.communicate(timeout=15)
        system.assert_reclaimed()
        client = PointCloudClient(
            buffers_root=system.settings.local_memory.root_dir,
            broker_settings=system.settings.local_buffer_broker,
        )
        reply = client.invoke_raster(
            source_id=system.source_id,
            generation=generation,
            raster=descriptor(),
            content=payload(),
            timeout_ms=30000,
            payload_key="cloud",
        )
        check_body(reply["response_payload"]["results"]["body"])
        system.assert_reclaimed()


@pytest.mark.skipif(
    os.name != "nt", reason="net472 SDK 仅支持 Windows；Ubuntu 验 Python 同机调用"
)
def test_raster_real_published_dotnet(tmp_path):
    desc = tmp_path / "raster.json"
    data = tmp_path / "raster.bin"
    desc.write_text(descriptor().model_dump_json(), encoding="utf-8")
    data.write_bytes(payload())
    with published_system(tmp_path) as system:
        system.start(system.publish(documents=raster_documents()))
        generation = system.enable_source(create=True)
        for mode in ("bytes", "fill"):
            result = subprocess.run(
                [
                    str(PROBE),
                    "--invoke-shared-memory-raster",
                    system.settings.local_memory.root_dir,
                    system.source_id,
                    str(generation),
                    str(desc),
                    str(data),
                    mode,
                ],
                capture_output=True,
                text=True,
                timeout=40,
            )
            assert result.returncode == 0, (result.stdout, result.stderr)
            reply = json.loads(result.stdout)
            assert reply["state"] == "succeeded", reply
            check_body(reply["response_payload"]["results"]["body"])
            system.assert_reclaimed()
