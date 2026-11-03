"""正式示例的完整文件/数组发布验收，不使用测试专用工作流。"""

import json
import platform
import time
from pathlib import Path
from urllib.parse import urlencode

import pytest

from scripts.metrology_workpiece import build_documents
from tests.integration.metrology3d.published_support import published_system
from tests.integration.metrology3d.representative_workflow import representative_policy
from tests.integration.metrology3d.test_published_runtime import sample_array
from runtimes.clients.point_cloud import PointCloudClient
from tests.point_cloud_support import spatial
from tests.integration.metrology3d.workpiece_workflow import check_record


@pytest.mark.parametrize("input_kind", ["array", "file"])
def test_public_workpiece_complete_delivery(tmp_path, request, input_kind):
    """两入口均走真实发布及独立 worker，数组同时验证三维/表格显示。"""
    sample = request.config.getoption("--cloud-sample")
    if not sample:
        pytest.skip("通过 --cloud-sample 显式提供完整样本")
    sample = Path(sample)
    view = "full" if input_kind == "array" else "numeric"
    binary = tmp_path / "cloud.bin"
    cloud = (
        sample_array(sample, binary).model_copy(update={"spatial": spatial()})
        if input_kind == "array"
        else None
    )
    with published_system(
        tmp_path, point_cloud_policy=representative_policy()
    ) as system:
        version = system.publish(
            point_limit=500_000,
            documents=build_documents(input_kind=input_kind, view=view),
        )
        system.start(version)
        started = time.monotonic()
        if input_kind == "array":
            generation = system.enable_source(create=True)
            snapshot = system.call(
                "GET", f"/app-runtimes/{system.runtime_id}/preview-snapshot"
            )
            query = urlencode(
                {
                    key: snapshot[key]
                    for key in (
                        "workflow_runtime_id",
                        "workflow_runtime_revision_id",
                        "runtime_generation",
                        "worker_instance_id",
                    )
                }
            )
            with system.client.websocket_connect(
                "/ws/v1/workflows/app-runtimes/preview?" + query, headers=system.headers
            ) as ws:
                assert ws.receive_json()["state"] == "connected"
                reply = PointCloudClient(
                    buffers_root=system.settings.local_memory.root_dir,
                    broker_settings=system.settings.local_buffer_broker,
                ).invoke(
                    source_id=system.source_id,
                    generation=generation,
                    cloud=cloud,
                    content=binary,
                    timeout_ms=120000,
                )
                assert reply["state"] == "succeeded", reply
                record = check_record(
                    reply["response_payload"]["results"]["body"], system
                )
                frame = ws.receive_json()
                ws.send_text("ready")
                assert frame["state"] == "succeeded" and not frame.get(
                    "display_error"
                ), frame.get("display_error")
                displays = [item["payload"] for item in frame["displays"]]
                display = next(
                    item for item in displays if item["type"] == "point-cloud-preview"
                )
                assert display["state"] == "ready", display
                assert display["display_point_count"] == 500_000
                assert len(display["measurements"]["items"]) == 50
                assert (
                    len(
                        [
                            c
                            for c in display["geometry"]["curves"]
                            if c["kind"] == "circle"
                        ]
                    )
                    == 2
                )
                assert len(displays) == 2
                ws.close()
                assert ws.receive()["type"] == "websocket.close"
        else:
            with sample.open("rb") as stream:
                reply = system.call(
                    "POST",
                    f"/app-runtimes/{system.runtime_id}/invoke/upload",
                    files={"cloud": (sample.name, stream, "application/octet-stream")},
                )
            assert reply["state"] == "succeeded", reply
            record = check_record(reply["results"]["body"], system)
        elapsed = time.monotonic() - started
        system.assert_reclaimed()
        assert (
            system.call("POST", f"/app-runtimes/{system.runtime_id}/stop")[
                "observed_state"
            ]
            == "stopped"
        )
        system.assert_reclaimed()
        output = request.config.getoption("--cloud-report-dir")
        if output:
            destination = Path(output)
            destination.mkdir(parents=True, exist_ok=True)
            (
                destination / f"delivery-{input_kind}-{platform.system().lower()}.json"
            ).write_text(
                json.dumps(
                    dict(
                        platform=platform.platform(),
                        input=input_kind,
                        view=view,
                        version=version,
                        item_count=50,
                        state=record["state"],
                        saved_matches_reply=True,
                        measurements_match_f4=True,
                        resources_reclaimed=True,
                        stopped=True,
                        elapsed_with_transfer_and_display_seconds=elapsed,
                    ),
                    indent=2,
                ),
                encoding="utf-8",
            )
