"""B09 实际算法的完整证据保存、关闭旧运行、空库搬运和恢复。"""

from dataclasses import replace
from io import BytesIO
from hashlib import sha256
import json
from zipfile import ZipFile, ZIP_STORED

import pytest

from backend.service.application.errors import InvalidRequestError
from backend.service.application.runtime.resource_scope import ResourceScope
from backend.service.application.workflows.point_cloud.runtime import get_cloud_runtime
from custom_nodes.metrology3d_nodes.shared.cloud_assets import read_asset, save_cloud
from custom_nodes.metrology3d_nodes.shared.edge_assets import read_edge
from custom_nodes.metrology3d_nodes.shared.edge_chains import build_edge_chains
from custom_nodes.metrology3d_nodes.shared.edge_normal_candidates import (
    normal_crease_candidates,
)
from custom_nodes.metrology3d_nodes.shared.edge_normal_runtime import (
    pair_normal_candidates,
    build_normal_edge_chains,
)
from custom_nodes.metrology3d_nodes.shared.edge_targets import select_edge_targets
from tests.point_cloud_support import create_resource_service
from tests.test_point_cloud_assets import POLICY as BASE_POLICY
from tests.test_metrology3d_edge_chains import prepare, chain_settings
from tests.test_metrology3d_edge_targets import selection
from tests.test_metrology3d_edge_normal_runtime import options, targets, evaluation
from tests.test_metrology3d_edge_normals import prepare as normal_prepare

POLICY = replace(
    BASE_POLICY, chunk_bytes=127, max_asset_bytes=2_000_000, max_archive_bytes=3_000_000
)


def fixture(kind, *, invalid=False, dtype="float64", flat=False):
    """生产算法构建独立解析台阶或折面，不伪造可通过的点对。"""
    if kind == "height-jump":
        scope, runtime, height, ref, _, pairs = prepare(dtype=dtype, slope=flat)
        cloud = ref.cloud
        chains = build_edge_chains(
            runtime, pairs, chain_settings(), cancel=lambda: None
        )
        result = select_edge_targets(
            runtime,
            chains,
            selection(length=10 if invalid else 0.01),
            cancel=lambda: None,
        )
    else:
        scope, runtime, _, cloud, settings = normal_prepare(dtype=dtype, flat=flat)
        height = None
        candidate = normal_crease_candidates(
            runtime, cloud, settings, cancel=lambda: None
        )
        pairs = pair_normal_candidates(
            runtime, candidate, options(kind), cancel=lambda: None
        )
        chains = build_normal_edge_chains(runtime, pairs, cancel=lambda: None)
        result = select_edge_targets(
            runtime,
            chains,
            targets(kind, length=10 if invalid else 0.1),
            evaluation=evaluation(),
            cancel=lambda: None,
        )
    return scope, runtime, cloud, height, result


def save(runtime, cloud, height, result, service, identity="a", cancel=lambda: None):
    """沿正式资源事务保存全部参与云和必要证据。"""
    return save_cloud(
        runtime,
        cloud,
        height_map=height,
        edge=result,
        service=service,
        project_id="test",
        name="edge",
        mode="derived",
        write_identity=identity * 64,
        policy=POLICY,
        cancel=cancel,
    )


@pytest.mark.parametrize("kind", ["height-jump", "a", "b"])
@pytest.mark.parametrize("invalid", [False, True])
@pytest.mark.parametrize("dtype", ["float32", "float64"])
def test_roundtrip_all_evidence_and_new_run(tmp_path, kind, invalid, dtype):
    scope, runtime, cloud, height, result = fixture(kind, invalid=invalid, dtype=dtype)
    other_scope = ResourceScope(kind="edge-restore")
    other = get_cloud_runtime(
        other_scope,
        run_id="restored",
        policy=runtime.policy.model_copy(update={"max_decoded_bytes": 2_000_000}),
    )
    service = create_resource_service(tmp_path / "source")
    target_service = create_resource_service(tmp_path / "target")
    try:
        expected = {}
        for name, obj in zip(
            ("candidates", "pairs", "chains", "targets"),
            (
                result.chains.pairs.candidates,
                result.chains.pairs,
                result.chains,
                result,
            ),
        ):
            with obj.borrow(runtime) as data:
                expected[name] = {k: a.tobytes() for k, a in data.items()}
        reference = save(runtime, cloud, height, result, service)
        archive = BytesIO()
        service.export_cloud_archive(
            reference,
            project_id="test",
            stream=archive,
            policy=POLICY,
            cancel=lambda: None,
        )
        assert scope.close() == () and runtime.budget.used == 0
        document = target_service.import_cloud_archive(
            stream=archive,
            project_id="test",
            name="imported",
            write_identity="b" * 64,
            policy=POLICY,
            cancel=lambda: None,
        )
        loaded = read_asset(
            other,
            document.reference,
            service=target_service,
            project_id="test",
            policy=POLICY,
            cancel=lambda: None,
        )
        restored = read_edge(
            other,
            loaded,
            document=document,
            service=target_service,
            project_id="test",
            policy=POLICY,
            cancel=lambda: None,
        )
        with restored.borrow(other) as groups:
            assert {
                g: {k: a.tobytes() for k, a in data.items()}
                for g, data in groups.items()
            } == expected
            assert all(
                not a.flags.writeable for data in groups.values() for a in data.values()
            )
        reports = restored.reports(loaded)
        assert (reports[0].reason is not None) == invalid
        assert reports[0].quality.metrics.observation_id == loaded.observation_id
        assert (
            save(other, loaded, None, restored, target_service, "c").sha256
            == document.reference.sha256
        )
        other.storage_scope.close_resource(restored.resource_key)
        with pytest.raises(InvalidRequestError), restored.borrow(other):
            pass
    finally:
        assert scope.close() == () and other_scope.close() == ()
        assert other.budget.used == 0


@pytest.mark.parametrize("phase", [1, 20, 100])
def test_cancel_read_releases_all_arrays(tmp_path, phase):
    scope, runtime, cloud, height, result = fixture("height-jump")
    service = create_resource_service(tmp_path)
    try:
        ref = save(runtime, cloud, height, result, service)
        runtime.policy = runtime.policy.model_copy(
            update={"max_decoded_bytes": 2_000_000}
        )
        loaded = read_asset(
            runtime,
            ref,
            service=service,
            project_id="test",
            policy=POLICY,
            cancel=lambda: None,
        )
        baseline = runtime.budget.used
        calls = 0

        def cancel():
            nonlocal calls
            calls += 1
            if calls == phase:
                raise InterruptedError("cancel-edge")

        with pytest.raises(InterruptedError):
            read_edge(
                runtime,
                loaded,
                document=service.read(ref, project_id="test"),
                service=service,
                project_id="test",
                policy=POLICY,
                cancel=cancel,
            )
        assert runtime.budget.used == baseline
    finally:
        assert scope.close() == ()


@pytest.mark.parametrize(
    "fault",
    [
        "short",
        "extra",
        "identity",
        "status",
        "partner",
        "reports",
        "supported",
        "paired",
    ],
)
def test_import_rejects_corruption_with_recomputed_digest(tmp_path, fault):
    """损坏长度、状态和行号不能仅靠重新计算摘要变成可用资产。"""
    import numpy as np

    scope, runtime, cloud, height, result = fixture("height-jump")
    service = create_resource_service(tmp_path)
    try:
        ref = save(runtime, cloud, height, result, service)
        archive = BytesIO()
        service.export_cloud_archive(
            ref, project_id="test", stream=archive, policy=POLICY, cancel=lambda: None
        )
        with ZipFile(archive) as z:
            files = {name: z.read(name) for name in z.namelist()}
        raw = json.loads(files["resource.json"])
        from backend.contracts.workflows.edge_evidence import EdgeEvidence

        evidence = EdgeEvidence.model_validate(raw["point_cloud"]["edge"])
        data = bytearray(files["edge.bin"])
        cursor = 0
        for group, name, dtype, count, width in evidence.layout():
            size = np.dtype(dtype).itemsize * count * width
            match = {
                "identity": "source_rows",
                "status": "status",
                "partner": "partners",
            }.get(fault)
            if group == "pairs" and name == match:
                values = np.frombuffer(
                    data, dtype=dtype, count=count * width, offset=cursor
                )
                values[0] = 999999 if fault != "status" else 255
            cursor += size
        if fault == "short":
            data = data[:-1]
        elif fault == "extra":
            data += b"x"
        elif fault == "reports":
            raw["point_cloud"]["edge"]["reports"][0]["target_id"] = "wrong-target"
        elif fault == "supported":
            raw["point_cloud"]["edge"]["supported_count"] -= 1
        elif fault == "paired":
            raw["point_cloud"]["edge"]["pair_count"] -= 1
        for blob in raw["point_cloud"]["blobs"]:
            if blob["role"] == "edge":
                blob["sha256"] = sha256(data).hexdigest()
        files["edge.bin"] = data
        files["resource.json"] = json.dumps(raw).encode()
        damaged = BytesIO()
        with ZipFile(damaged, "w", compression=ZIP_STORED) as z:
            for name, body in files.items():
                z.writestr(name, body)
        with pytest.raises(InvalidRequestError):
            service.import_cloud_archive(
                stream=damaged,
                project_id="empty",
                name="bad",
                write_identity="d" * 64,
                policy=replace(POLICY, chunk_bytes=7),
                cancel=lambda: None,
            )
        assert service.list_versions(project_id="empty") == []
    finally:
        assert scope.close() == ()


def test_commit_cancel_rolls_back_blobs(tmp_path, monkeypatch):
    """保存末端取消不能留下可见版本或半份证据。"""
    scope, runtime, cloud, height, result = fixture("a")
    service = create_resource_service(tmp_path)
    original = service.storage.write_json

    def cancel_commit(key, value, *args, **kwargs):
        if key.endswith("version.json"):
            raise InterruptedError("commit")
        return original(key, value, *args, **kwargs)

    try:
        monkeypatch.setattr(service.storage, "write_json", cancel_commit)
        baseline = runtime.budget.used
        with pytest.raises(InterruptedError):
            save(runtime, cloud, height, result, service)
        assert service.list_versions(project_id="test") == []
        assert not list(tmp_path.rglob("content.bin"))
        assert runtime.budget.used == baseline
    finally:
        assert scope.close() == ()


def test_recipe_package_remaps_edge_asset(tmp_path):
    """A10 依赖闭包搬运完整失败证据，不借旧库或旧运行读取。"""
    from backend.contracts.workflows.cloud_package import WorkflowAppDocument
    from backend.service.application.workflows.cloud_package import export_cloud_package
    from backend.service.application.workflows.documents.measurement_resources import (
        reference_key,
    )
    from tests.test_workflow_cloud_package import workflow_service, import_package
    from tests.integration.metrology3d.test_height_map_published import documents

    scope, runtime, cloud, height, result = fixture("height-jump", invalid=True)
    service = create_resource_service(tmp_path / "source")
    other = create_resource_service(tmp_path / "target")
    try:
        ref = save(runtime, cloud, height, result, service)
        template, application = documents(reference=ref.model_dump(mode="json"))
        stream = BytesIO()
        export_cloud_package(
            workflow_service(service),
            WorkflowAppDocument(
                format_id="amvision.workflow-app-document.v1",
                template=template,
                application=application,
            ),
            project_id="test",
            stream=stream,
            policy=POLICY,
            cancel=lambda: None,
        )
        _, mapping = import_package(other, POLICY, stream.getvalue())
        mapped = mapping[reference_key(ref)]
        assert mapped != ref
        runtime.policy = runtime.policy.model_copy(
            update={"max_decoded_bytes": 2_000_000}
        )
        loaded = read_asset(
            runtime,
            mapped,
            service=other,
            project_id="target",
            policy=POLICY,
            cancel=lambda: None,
        )
        restored = read_edge(
            runtime,
            loaded,
            document=other.read(mapped, project_id="target"),
            service=other,
            project_id="target",
            policy=POLICY,
            cancel=lambda: None,
        )
        assert (
            restored.reports(loaded)[0].reason
            == result.reason
            == "insufficient_quality"
        )
        with (
            restored.borrow(runtime) as groups,
            result.chains.pairs.borrow(runtime) as original,
        ):
            assert (
                groups["pairs"]["source_rows"].tobytes()
                == original["source_rows"].tobytes()
            )
    finally:
        assert scope.close() == ()


def test_restore_budget_and_wrong_parent_rejected(tmp_path):
    """禁止预算越界分配，禁止从另一云借用有效证据。"""
    scope, runtime, cloud, height, result = fixture("height-jump")
    service = create_resource_service(tmp_path)
    try:
        ref = save(runtime, cloud, height, result, service)
        runtime.policy = runtime.policy.model_copy(
            update={"max_decoded_bytes": 2_000_000}
        )
        loaded = read_asset(
            runtime,
            ref,
            service=service,
            project_id="test",
            policy=POLICY,
            cancel=lambda: None,
        )
        document = service.read(ref, project_id="test")
        baseline = runtime.budget.used
        with pytest.raises(InvalidRequestError, match="身份"):
            read_edge(
                runtime,
                cloud,
                document=document,
                service=service,
                project_id="test",
                policy=POLICY,
                cancel=lambda: None,
            )
        runtime.policy = runtime.policy.model_copy(update={"max_decoded_bytes": 1})
        with pytest.raises(InvalidRequestError, match="容量"):
            read_edge(
                runtime,
                loaded,
                document=document,
                service=service,
                project_id="test",
                policy=POLICY,
                cancel=lambda: None,
            )
        assert runtime.budget.used == baseline
    finally:
        assert scope.close() == ()


@pytest.mark.parametrize("kind", ["height-jump", "a"])
def test_no_supported_edge_preserves_empty_geometry_and_failures(tmp_path, kind):
    """平滑面不能因保存读取而变成可测边；零长度字段仍严格按布局处理。"""
    scope, runtime, cloud, height, result = fixture(kind, flat=True)
    service = create_resource_service(tmp_path)
    try:
        assert result.reason is not None
        ref = save(runtime, cloud, height, result, service)
        runtime.policy = runtime.policy.model_copy(
            update={"max_decoded_bytes": 2_000_000}
        )
        loaded = read_asset(
            runtime,
            ref,
            service=service,
            project_id="test",
            policy=POLICY,
            cancel=lambda: None,
        )
        restored = read_edge(
            runtime,
            loaded,
            document=service.read(ref, project_id="test"),
            service=service,
            project_id="test",
            policy=POLICY,
            cancel=lambda: None,
        )
        assert restored.reports(loaded)[0].reason == result.reason
        assert restored.reports(loaded)[0].topology is None
        with restored.borrow(runtime) as groups:
            assert groups["targets"]["chain_rows"].shape == (0, 1)
            assert groups["chains"]["positions"].shape == (0, 3)
    finally:
        assert scope.close() == ()
