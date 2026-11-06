"""B07 资产进入已有正式节点和独立 worker；不冒称新轮廓 Trigger 已交付。"""

from dataclasses import replace
from io import BytesIO

import numpy as np

from backend.contracts.workflows.point_cloud_runtime import FilterCloudValid
from backend.contracts.workflows.workflow_graph import (
    WorkflowGraphTemplate,
    FlowApplication,
)
from backend.service.application.runtime.resource_scope import ResourceScope
from backend.service.application.workflows.point_cloud.runtime import get_cloud_runtime
from backend.service.application.workflows.documents.cloud_resource_archives import (
    export_cloud_archive,
)
from custom_nodes.metrology3d_nodes.shared.filter_valid import filter_valid
from tests.point_cloud_support import create_resource_service, options, policy
from tests.test_metrology3d_profile_runtime import source
from tests.test_metrology3d_raster_runtime import save, POLICY
from tests.test_metrology3d_preview import decode
from tests.metrology3d_transport_support import cloud_documents
from tests.integration.metrology3d.published_support import published_system


def profile_archive(root):
    """使用真实转换和保存生成独立资产，所有运行引用在导入前已关闭。"""
    scope = ResourceScope(kind="profile-asset-input")
    runtime = get_cloud_runtime(scope, run_id="profile-source", policy=policy())
    service = create_resource_service(root)
    try:
        cloud, _ = source(runtime, service, entry="array", method="fixed-step")
        filtered, _ = filter_valid(
            runtime,
            cloud,
            FilterCloudValid(finite_fields=("positions",), sentinels=()),
            cancel=lambda: None,
        )
        reference = save(runtime, filtered, service, "derived", "a")
        stream = BytesIO()
        export_cloud_archive(
            service,
            reference,
            project_id="test",
            stream=stream,
            policy=replace(POLICY, max_archive_bytes=65536),
            cancel=lambda: None,
        )
        return stream.getvalue()
    finally:
        assert scope.close() == () and runtime.budget.used == 0


def documents(reference):
    """复用 Read/Filter/Preview/Save 节点，不添加测试 handler 或绕过发布准入。"""
    template, app = cloud_documents(options().model_dump(mode="json"))
    graph, application = template.model_dump(mode="json"), app.model_dump(mode="json")
    graph["nodes"][0]["parameters"] = {
        "source": {"kind": "asset", "reference": reference}
    }
    graph["template_inputs"] = []
    application["bindings"] = [
        b for b in application["bindings"] if b["direction"] == "output"
    ]
    graph["nodes"].append(
        dict(
            node_id="save",
            node_type_id="custom.metrology3d.save-cloud",
            parameters=dict(mode="derived", target=dict(kind="new", name="Profiles")),
        )
    )
    graph["edges"].append(
        dict(
            edge_id="save-profile",
            source_node_id="filter",
            source_port="cloud",
            target_node_id="save",
            target_port="cloud",
        )
    )
    return WorkflowGraphTemplate.model_validate(graph), FlowApplication.model_validate(
        application
    )


def test_profile_asset_api_import_publish_save_restart(tmp_path):
    """空环境 ZIP 导入、三代发布/独立计算、保存与切版，验证来源和回收。"""
    payload = profile_archive(tmp_path / "source")
    with published_system(tmp_path / "target") as system:
        response = system.client.post(
            system.base + "/projects/project-1/measurement-resources/cloud/import",
            params={"name": "Profiles"},
            content=payload,
            headers={
                **system.headers,
                "Content-Type": "application/zip",
                "Idempotency-Key": "profiles",
            },
        )
        assert response.status_code == 201, response.text
        document = response.json()
        reference = document["reference"]
        row_sha = document["content"]["point_cloud"]["indices"]["source"][
            "row_table_sha256"
        ]
        seen = {reference["resource_id"]}
        for generation in range(3):
            version = system.publish(documents=documents(reference))
            if generation:
                system.call("POST", f"/app-runtimes/{system.runtime_id}/stop")
                system.call(
                    "POST",
                    f"/app-runtimes/{system.runtime_id}/select-version",
                    json={
                        "workflow_app_version_id": version,
                        "expected_generation": generation,
                    },
                )
            system.start(version if not generation else None)
            reply = system.call(
                "POST",
                f"/app-runtimes/{system.runtime_id}/invoke",
                json={
                    "input_bindings": {},
                    "execution_metadata": {},
                },
            )
            assert reply["state"] == "succeeded", reply
            body = reply["results"]["body"]
            assert body["source_point_count"] == 6 and body["point_count"] == 5
            points = decode(body)
            np.testing.assert_array_equal(
                points["source_indices"][:, 0], [1, 2, 3, 4, 5]
            )
            raw = np.array(
                [[2, 3], [3, 4], [4, 0], [5, -1], [6, np.float32(0.123456789)]]
            )
            expected = (
                np.array([10, 20, 30])
                + raw[:, :1] * [0.6, 0.8, 0]
                + raw[:, 1:] * [0.8, -0.6, 0]
            )
            expected[:, 2] += (np.array([3, 8, 8, 8, 9]) - 5) * 2
            np.testing.assert_allclose(points["positions"], expected, atol=2e-6)
            versions = system.call("GET", "/projects/project-1/measurement-resources")
            assert len(versions) == generation + 2
            reference = next(
                r["reference"]
                for r in versions
                if r["reference"]["resource_id"] not in seen
            )
            seen.add(reference["resource_id"])
            resource = system.call(
                "GET",
                f"/projects/project-1/measurement-resources/{reference['resource_id']}/versions/{reference['version']}",
            )
            cloud = resource["content"]["point_cloud"]
            assert cloud["indices"]["source_point_count"] == 6
            assert cloud["indices"]["source"]["row_table_sha256"] == row_sha
            assert (
                next(b for b in cloud["blobs"] if b["role"] == "profile-rows")["sha256"]
                == row_sha
            )
            system.assert_reclaimed()
        system.call("POST", f"/app-runtimes/{system.runtime_id}/stop")
        system.assert_reclaimed()
