"""B07 正式节点、发布版本、独立 worker 和实际 Trigger，不替换控制面准入。"""

from concurrent.futures import CancelledError
from io import BytesIO
import json
import os
import subprocess
import sys

import numpy as np
import pytest

from backend.contracts.workflows.profile3d import ProfileBufferDescriptor
from backend.contracts.workflows.workflow_graph import (
    WorkflowGraphTemplate,
    FlowApplication,
)
from runtimes.clients.point_cloud import PointCloudClient, PointCloudCallError
from tests.metrology3d_transport_support import cloud_documents
from tests.integration.metrology3d.published_support import published_system
from tests.integration.metrology3d.published_client import wait_for
from tests.integration.metrology3d.test_published_runtime import PROBE
from tests.test_metrology3d_preview import decode
from tests.test_metrology3d_profile_conversion import specification, inputs


def profile_case(method="fixed-step", dtype="float32"):
    """仅用于解析真值；空采集行保留，编码器倒向和重复位置合法。"""
    spec = specification(
        dtype=dtype,
        displacement=(
            dict(kind="encoder-positions", dtype="float64", scale=0.5, origin=10)
            if method == "encoder-positions"
            else dict(kind="fixed-step", origin_line_id=5, step=2)
        ),
    )
    arrays = inputs(
        dtype, [12, np.nan, 8, 8] if method == "encoder-positions" else None
    )
    descriptor = ProfileBufferDescriptor(
        format_id="amvision.profile-buffer.v1",
        profiles=spec,
        has_validity=False,
        content_length=spec.input_bytes(has_validity=False),
    )
    content = b"".join(
        arrays[name].tobytes() for name, _, _ in spec.input_layout(has_validity=False)
    )
    stream = BytesIO()
    np.savez(stream, **arrays)
    return descriptor, content, stream.getvalue()


def profile_documents(spec=None):
    """只增加真实轮廓转换节点，其余复用既有 Filter/Preview 和 App binding。"""
    template, app = cloud_documents()
    graph = template.model_dump(mode="json")
    settings = (
        {"kind": "local-array"}
        if spec is None
        else dict(
            kind="file",
            file_format="npz",
            profiles=spec.model_dump(mode="json"),
            has_validity=False,
        )
    )
    graph["nodes"].insert(
        0,
        dict(
            node_id="profiles",
            node_type_id="custom.metrology3d.profiles-to-cloud",
            parameters={"settings": settings},
        ),
    )
    graph["template_inputs"][0].update(
        payload_type_id="calibrated-profiles.v1" if spec is None else "file-ref.v1",
        target_node_id="profiles",
        target_port="profiles" if spec is None else "file",
    )
    graph["edges"].append(
        dict(
            edge_id="profiles-filter",
            source_node_id="profiles",
            source_port="cloud",
            target_node_id="filter",
            target_port="cloud",
        )
    )
    application = app.model_dump(mode="json")
    if spec is not None:
        application["bindings"][0]["config"] = dict(
            allowed_media_types=["application/octet-stream"],
            max_file_bytes=1_000_000_000,
        )
    return WorkflowGraphTemplate.model_validate(graph), FlowApplication.model_validate(
        application
    )


def check_profile_body(body, desc):
    """解析坐标独立计算，不用转换实现产生预期值。"""
    assert body["source_point_count"] == body["point_count"] == 6
    assert body["profile_source"]["profile_count"] == 4
    assert body["profile_empty_count"] == 1
    values = decode(body)
    np.testing.assert_array_equal(
        values["acquisition_line_id"][:, 0], [3, 3, 8, 8, 8, 9]
    )
    np.testing.assert_array_equal(
        values["profile_sample_index"][:, 0], [0, 1, 0, 1, 2, 0]
    )
    np.testing.assert_array_equal(values["source_indices"][:, 0], np.arange(6))
    raw = inputs(desc.profiles.dtype)["profiles"]
    distance = (
        [-4, -4, 6, 6, 6, 8]
        if desc.profiles.displacement.kind == "fixed-step"
        else [1, 1, -1, -1, -1, -1]
    )
    expected = [
        [
            10 + float(x) * 0.6 + float(h) * 0.8,
            20 + float(x) * 0.8 - float(h) * 0.6,
            30 + d,
        ]
        for (x, h), d in zip(raw, distance)
    ]
    np.testing.assert_allclose(values["positions"], expected, atol=2e-6)


@pytest.mark.parametrize("method", ["fixed-step", "encoder-positions"])
def test_profiles_python_published_lifecycle(tmp_path, method):
    desc, content, _ = profile_case(method)
    with published_system(tmp_path) as system:
        version = system.publish(documents=profile_documents())
        runtime = system.start(version)
        generation = system.enable_source(create=True)
        client = PointCloudClient(
            buffers_root=system.settings.local_memory.root_dir,
            broker_settings=system.settings.local_buffer_broker,
        )
        kwargs = dict(
            source_id=system.source_id,
            generation=generation,
            profiles=desc,
            content=content,
            timeout_ms=30000,
            payload_key="cloud",
        )

        def invoke(**overrides):
            reply = client.invoke_profiles(**(kwargs | overrides))
            assert reply["state"] == "succeeded", reply
            check_profile_body(reply["response_payload"]["results"]["body"], desc)
            system.assert_reclaimed()
            return reply

        reply = invoke()
        run = system.call("GET", f"/runs/{reply['workflow_run_id']}?response_mode=run")
        assert run["workflow_app_version_id"] == version
        assert run["worker_instance_id"] == runtime["worker_instance_id"]
        with pytest.raises(ValueError):
            invoke(payload={"cloud": {}})
        checks = 0

        def cancel():
            nonlocal checks
            checks += 1
            return checks >= 2

        with pytest.raises(CancelledError):
            invoke(cancelled=cancel)
        system.assert_reclaimed()
        with pytest.raises(PointCloudCallError):
            invoke(generation=generation + 1)
        system.assert_reclaimed()
        version2 = system.publish(point_limit=500, documents=profile_documents())
        system.call("POST", f"/app-runtimes/{system.runtime_id}/stop")
        system.call("POST", f"/trigger-sources/{system.source_id}/disable")
        system.call(
            "POST",
            f"/app-runtimes/{system.runtime_id}/select-version",
            json={"workflow_app_version_id": version2, "expected_generation": 1},
        )
        system.start()
        invoke(generation=system.enable_source())


def test_profiles_writer_crash_recovers(tmp_path):
    """真实 WRITING 持有者异常退出；回收后同一发布仍可调用。"""
    desc, content, _ = profile_case()
    dp, data, ready = (
        tmp_path / "profiles.json",
        tmp_path / "profiles.bin",
        tmp_path / "writer-ready",
    )
    dp.write_text(desc.model_dump_json(), encoding="utf-8")
    data.write_bytes(content)
    with published_system(tmp_path / "system") as system:
        system.start(system.publish(documents=profile_documents()))
        generation = system.enable_source(create=True)
        args = [
            system.settings.local_memory.root_dir,
            system.source_id,
            str(generation),
            str(dp),
            str(data),
            "hold-writer",
            "5000",
            str(ready),
        ]
        command = (
            [str(PROBE), "--invoke-shared-memory-profiles", *args]
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
        reply = client.invoke_profiles(
            source_id=system.source_id,
            generation=generation,
            profiles=desc,
            content=content,
            timeout_ms=30000,
            payload_key="cloud",
        )
        assert reply["state"] == "succeeded", reply
        check_profile_body(reply["response_payload"]["results"]["body"], desc)
        system.assert_reclaimed()


@pytest.mark.parametrize(
    "method,dtype", [("fixed-step", "float32"), ("encoder-positions", "float64")]
)
def test_profiles_file_published_bad_then_good(tmp_path, method, dtype):
    desc, _, file = profile_case(method, dtype)
    with published_system(tmp_path) as system:
        system.start(system.publish(documents=profile_documents(desc.profiles)))
        for content, state in [(file[:20], "failed"), (file, "succeeded")]:
            reply = system.call(
                "POST",
                f"/app-runtimes/{system.runtime_id}/invoke/upload",
                files={"cloud": ("profiles.npz", content, "application/octet-stream")},
            )
            assert reply["state"] == state, reply
            if state == "succeeded":
                check_profile_body(reply["results"]["body"], desc)
            system.assert_reclaimed()


@pytest.mark.skipif(
    os.name != "nt", reason="net472 仅验 Windows；Ubuntu 使用正式 Python 工具"
)
def test_profiles_dotnet_published(tmp_path):
    desc, content, _ = profile_case("encoder-positions", "float64")
    dp, data = tmp_path / "profiles.json", tmp_path / "profiles.bin"
    dp.write_text(desc.model_dump_json(), encoding="utf-8")
    data.write_bytes(content)
    with published_system(tmp_path / "system") as system:
        system.start(system.publish(documents=profile_documents()))
        generation = system.enable_source(create=True)
        for mode in ("bytes", "fill"):
            result = subprocess.run(
                [
                    str(PROBE),
                    "--invoke-shared-memory-profiles",
                    system.settings.local_memory.root_dir,
                    system.source_id,
                    str(generation),
                    str(dp),
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
            check_profile_body(reply["response_payload"]["results"]["body"], desc)
            system.assert_reclaimed()
