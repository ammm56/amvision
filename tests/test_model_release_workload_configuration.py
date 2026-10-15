"""模型验收使用真实部署配置，并把诊断输出与普通性能样本隔离。"""

from dataclasses import replace

import pytest

from backend.service.domain.deployments.deployment_runtime_configuration import (
    build_default_runtime_configuration, serialize_deployment_runtime_configuration,
)
from tests.integration.model_matrix_release_workload import create_model_workflow, read_import_runtime_configuration


@pytest.mark.parametrize("count", [1, 2, 4])
def test_import_keeps_package_configuration(count: int) -> None:
    """容量来自被测部署包，不能写死为一或二，也不能丢失生命周期配置。"""
    original = build_default_runtime_configuration(runtime_backend="tensorrt", device_name="cuda:0")
    original = replace(original, execution=replace(original.execution, instance_count=count),
                       lifecycle=replace(original.lifecycle, keep_warm_enabled=False))
    uploaded = {"summary": {"deployment": {"runtime_backend": "tensorrt",
        "runtime_configuration": serialize_deployment_runtime_configuration(original)}}}
    assert read_import_runtime_configuration(uploaded, runtime_backend="tensorrt") == original
    with pytest.raises(ValueError, match="runtime"):
        read_import_runtime_configuration(uploaded, runtime_backend="openvino")


@pytest.mark.parametrize("diagnostics", [False, True])
def test_model_diagnostics_are_opt_in(diagnostics: bool) -> None:
    """仅诊断图返回模型 timing，正式默认输出不能被诊断信息改变。"""
    class Client:
        """记录通过公开 API 提交的工作流。"""
        document = None

        def put(self, _path, *, json):
            """保留模板请求以核对输出选择。"""
            self.document = json

        def post(self, _path, **_kwargs):
            """返回测试 Runtime 标识。"""
            return {"workflow_runtime_id": "runtime-test"}

    client = Client()
    create_model_workflow(client, task="segmentation", deployment="deployment", diagnostics=diagnostics)
    paths = client.document["template"]["nodes"][-1]["parameters"]["paths"]
    assert paths == (["items", "metadata", "latency_ms", "runtime_session_info"] if diagnostics else ["items"])
