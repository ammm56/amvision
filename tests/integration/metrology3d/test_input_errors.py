"""真实解析/GraphExecutor/独立发布 Runtime 保留输入错误，不改变清理边界。"""

import pytest

from backend.service.application.errors import (
    ServiceConfigurationError,
    WorkflowInputError,
)
from backend.service.application.runtime.resource_scope import (
    get_or_create_workflow_resource_scope,
)
from backend.service.application.workflows.graph_executor import WorkflowGraphExecutor
from backend.service.application.workflows.service_runtime.context import (
    WorkflowServiceNodeRuntimeContext,
)
from custom_nodes.metrology3d_nodes.shared.io.formats import (
    require_controlled_distribution,
)
from custom_nodes.metrology3d_nodes.shared.io.input_errors import parsing_input
from tests.integration.metrology3d.test_file_read import (
    context as context,
    ply,
    publish,
    run,
)
from tests.integration.metrology3d.test_nodes import build_chain, execution_policy
from tests.point_cloud_support import create_resource_service, options, policy


@pytest.mark.parametrize(
    "content,profile",
    [
        (b"not-ply\n", "ply-ascii"),
        (b"VERSION .7\nDATA ascii\n", "pcd-ascii"),
        (b"\xff", "xyz-whitespace"),
    ],
)
def test_header_errors_are_typed_and_release(context, content, profile):
    """不回显无界输入，不产生可用数组。"""
    with pytest.raises(WorkflowInputError) as failure:
        run(context, content, options(profile))
    assert failure.value.code == "workflow_input_point_cloud_header_invalid"
    assert failure.value.status_code == 400
    assert len(failure.value.details["parser_error"]) <= 512
    assert context[2].used == 0


def test_header_limit_is_not_classified_as_corrupt_data(context):
    """受控解析器的 header 预算仍是限额拒绝。"""
    storage, _, budget, scope = context
    with pytest.raises(WorkflowInputError) as failure:
        run((storage, policy(max_header_bytes=16), budget, scope), ply())
    assert failure.value.code == "workflow_input_point_cloud_limit_exceeded"
    assert budget.used == 0


@pytest.mark.parametrize(
    "encoding,body",
    [
        ("ascii", b"1 bad 3\n4 5 6\n"),
        ("ascii", b"1 2 3\n"),
        ("binary", b"\0" * 23),
        ("binary_compressed", b"\x01\x00\x00\x00\x18\x00\x00\x00"),
    ],
)
def test_pcd_truncated_or_invalid_body_retains_input_classification(
    context, encoding, body
):
    """ASCII、二进制、压缩体均拒绝半条记录，失败释放仍由既有 Scope 承担。"""
    header = (
        "VERSION .7\nFIELDS x y z\nSIZE 4 4 4\nTYPE F F F\nCOUNT 1 1 1\n"
        f"WIDTH 2\nHEIGHT 1\nVIEWPOINT 0 0 0 1 0 0 0\nPOINTS 2\nDATA {encoding}\n"
    ).encode()
    with pytest.raises(WorkflowInputError) as failure:
        run(context, header + body, options("pcd-" + encoding.replace("_", "-")))
    assert failure.value.code == "workflow_input_point_cloud_data_invalid"
    assert context[2].used == 0 and context[3].resource_count == 0


@pytest.mark.parametrize(
    "error",
    [
        RuntimeError("internal"),
        MemoryError("allocation"),
        OSError("disk"),
        InterruptedError("cancel"),
        TimeoutError("deadline"),
        ServiceConfigurationError("dependency"),
    ],
)
def test_non_input_failures_are_not_downgraded(error):
    """只翻译解析器声明的值错误，不全局吞掉异常。"""
    with pytest.raises(type(error)) as failure:
        with parsing_input("ply-ascii", "data"):
            raise error
    assert failure.value is error


def test_missing_distribution_remains_configuration_error():
    """依赖缺失不是坏文件，也不改用其他读取器。"""
    with pytest.raises(ServiceConfigurationError) as failure:
        require_controlled_distribution(
            "amvision-nonexistent-io-test-distribution", "1"
        )
    assert failure.value.details["actual_version"] is None


def test_graph_executor_preserves_profile_error_and_releases(tmp_path):
    """经真实 handler 后错误码不再变为节点内部配置错误。"""
    service = create_resource_service(tmp_path)
    runtime_context = WorkflowServiceNodeRuntimeContext(
        session_factory=None,
        dataset_storage=service.storage,
        point_cloud_policy=execution_policy(),
    )
    registry, template = build_chain()
    template.nodes[0].parameters["file_options"] = options("ply-binary-le").model_dump(
        mode="json"
    )
    metadata = dict(project_id="test", workflow_run_id="invalid-profile")
    scope = get_or_create_workflow_resource_scope(metadata)
    try:
        with pytest.raises(WorkflowInputError) as failure:
            WorkflowGraphExecutor(registry=registry).execute(
                template=template,
                input_values={"file": publish(service.storage, ply())},
                execution_metadata=metadata,
                runtime_context=runtime_context,
            )
        assert failure.value.code == "workflow_input_point_cloud_format_mismatch"
        assert failure.value.details["expected_encoding"] == "binary_little_endian"
    finally:
        assert scope.close() == ()


def test_published_runtime_reports_bad_input_and_recovers(tmp_path):
    """独立 worker 上传坏文件、返回输入错误后仍能接收正常文件。"""
    from tests.integration.metrology3d.published_support import published_system
    from tests.metrology3d_transport_support import cloud_documents

    with published_system(tmp_path) as system:
        version = system.publish(
            documents=cloud_documents(options().model_dump(mode="json"))
        )
        system.start(version)
        for body, expected in [
            (ply(b"1 bad 3\n4 5 6\n"), "failed"),
            (ply(), "succeeded"),
        ]:
            response = system.call(
                "POST",
                f"/app-runtimes/{system.runtime_id}/invoke/upload?response_mode=run",
                files={"cloud": ("input.ply", body, "application/octet-stream")},
            )
            assert response["state"] == expected, response
            if expected == "failed":
                assert (
                    response["error"]["code"]
                    == "workflow_input_point_cloud_data_invalid"
                )
            system.assert_reclaimed()
        stopped = system.call("POST", f"/app-runtimes/{system.runtime_id}/stop")
        assert stopped["observed_state"] == "stopped"
        assert stopped["worker_process_id"] is None
