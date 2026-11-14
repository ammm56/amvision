"""完整工件经正式偏差节点发布运行；同一次证据用于真实页面，不替换处理器。"""

import argparse
import json
from pathlib import Path

from backend.contracts.workflows.workflow_graph import (
    WorkflowGraphTemplate,
    FlowApplication,
)
from tests.metrology3d_transport_support import cloud_documents
from tests.point_cloud_support import options
from tests.integration.metrology3d.published_support import published_system
from tests.integration.metrology3d.representative_workflow import representative_policy
from tests.integration.metrology3d.package_acceptance import serve
from tests.integration.metrology3d.full_cloud_sample import FILE_SHA
from tests.test_metrology3d_datum_deviation import parameters
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
    DatasetStorageSettings,
)


def documents():
    """直接复用交付工件 D/T ROI、拟面与有限延伸规则，不写入报告参考值。"""
    template, app = cloud_documents(options().model_dump(mode="json"))
    graph = template.model_dump(mode="json")
    formal = json.loads(
        (
            Path(__file__).resolve().parents[3]
            / "docs/examples/workflows/lithium_workpiece.template.json"
        ).read_text("utf-8")
    )
    nodes = {n["node_id"]: n for n in formal["nodes"]}
    graph["nodes"] += [nodes[k] for k in ("D-crop", "D", "A_top_L.T-crop")]
    mode = nodes["A_top_L.Z"]["parameters"]["settings"]["mode"]
    quality = dict(mode["quality_policy"])
    quality["rules"] = [
        r for r in quality["rules"] if r["item_id"].startswith("reference_")
    ]
    configured = parameters(
        reference_feature_id="D",
        support_radius=mode["support_radius"],
        reference_policy=mode["reference_policy"],
        quality_policy=quality,
    )
    graph["nodes"].append(
        dict(
            node_id="deviation",
            node_type_id="custom.metrology3d.measure-deviation",
            parameters=dict(settings=configured.model_dump(mode="json")),
        )
    )
    for a, b, c, d in (
        ("filter", "cloud", "D-crop", "cloud"),
        ("D-crop", "cloud", "D", "cloud"),
        ("filter", "cloud", "A_top_L.T-crop", "cloud"),
        ("A_top_L.T-crop", "cloud", "deviation", "cloud"),
        ("D", "features", "deviation", "features"),
        ("deviation", "evidence", "preview", "evidence"),
        ("D", "features", "preview", "features"),
    ):
        graph["edges"].append(
            dict(
                edge_id=f"deviation-{len(graph['edges'])}",
                source_node_id=a,
                source_port=b,
                target_node_id=c,
                target_port=d,
            )
        )
    graph["nodes"].append(
        dict(
            node_id="response",
            node_type_id="core.output.http-response",
            parameters={"status_code": 200},
        )
    )
    graph["edges"].append(
        dict(
            edge_id="public-response",
            source_node_id="preview",
            source_port="body",
            target_node_id="response",
            target_port="body",
        )
    )
    graph["template_outputs"] = [
        dict(
            output_id="http_response",
            display_name="Response",
            payload_type_id="http-response.v1",
            source_node_id="response",
            source_port="response",
        )
    ]
    application = app.model_dump(mode="json")
    application["bindings"][1].update(
        binding_id="http_response", template_port_id="http_response"
    )
    return WorkflowGraphTemplate.model_validate(graph), FlowApplication.model_validate(
        application
    )


def run(root, sample, port=None):
    """正式 API 创建/发布，独立 Runtime 执行，停止恢复后再次核对五项。"""
    with published_system(root, point_cloud_policy=representative_policy()) as system:
        storage = LocalDatasetStorage(
            DatasetStorageSettings(root_dir=system.settings.dataset_storage.root_dir)
        )
        with sample.open("rb") as stream:
            meta = storage.write_immutable_stream(
                object_prefix="projects/project-1/results/cloud",
                source_stream=stream,
                media_type="application/octet-stream",
                extension="ply",
            ).metadata
        assert meta.checksum == FILE_SHA
        file = dict(
            transport_kind="storage",
            storage_ref="object-store",
            object_key=meta.object_key,
            file_name=sample.name,
            media_type=meta.media_type,
            content_length=meta.content_length,
            checksum_algorithm="sha256",
            checksum=meta.checksum,
            immutable_version=meta.immutable_version,
        )
        version = system.publish(documents=documents(), point_limit=100000)
        system.start(version)

        def invoke():
            result = system.call(
                "POST",
                f"/app-runtimes/{system.runtime_id}/invoke?response_mode=run",
                json=dict(input_bindings={"cloud": file}, execution_metadata={}),
            )
            assert result["state"] == "succeeded", result
            body = result["outputs"]["http_response"]["body"]
            items = body["measurements"]["items"]
            assert len(items) == 5 and all(i["valid"] for i in items)
            assert items[0]["summary"]["target_count"] == 7656
            expected = {
                "min": 1.5497509214947627,
                "max": 1.6077374511653115,
                "peak-to-valley": 0.05798652967054885,
                "mean": 1.578792216471133,
                "rms": 1.5788151076376893,
            }
            assert all(
                abs(i["value"] - expected[i["component"]]) < 1e-10 for i in items
            )
            system.assert_reclaimed()
            return result, body

        first, body = invoke()
        stopped = system.call("POST", f"/app-runtimes/{system.runtime_id}/stop")
        assert stopped["observed_state"] == "stopped"
        system.start()
        second, body = invoke()
        assert first["workflow_run_id"] != second["workflow_run_id"]
        (root / "display.json").write_text(
            json.dumps(body, ensure_ascii=False), encoding="utf-8"
        )
        (root / "acceptance.json").write_text(
            json.dumps(
                dict(
                    version=version,
                    runtime_id=system.runtime_id,
                    file=file,
                    items=body["measurements"]["items"],
                ),
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(
            json.dumps(
                dict(
                    status="passed",
                    version=version,
                    items=5,
                    targets=7656,
                    stopped_and_restarted=True,
                )
            ),
            flush=True,
        )
        if port:
            serve(system, root, port)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--sample", type=Path, required=True)
    parser.add_argument("--serve", type=int)
    args = parser.parse_args()
    if args.serve and (args.serve in (5600, 5601) or not 1024 <= args.serve <= 65535):
        parser.error("必须使用隔离端口")
    args.root = args.root.resolve()
    args.root.mkdir(parents=True, exist_ok=False)
    run(args.root, args.sample, args.serve)
