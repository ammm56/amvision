"""验证 .NET SDK name/id 入口和 Console 示例保持完整。"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SDK_ROOT = ROOT / "sdks" / "dotnet" / "src" / "Amvar.Vision"
CONSOLE_ROOT = ROOT / "sdks" / "dotnet" / "apps" / "AMVision.Console"
CONSOLE_PROGRAM = CONSOLE_ROOT / "Program.cs"
CONSOLE_ID_CALLS = CONSOLE_ROOT / "ResourceIdSdkCalls.cs"
CONSOLE_NAME_CALLS = CONSOLE_ROOT / "KeyNameSdkCalls.cs"

EXPECTED_BY_ID_METHODS = {
    "ListProjectRuntimesByIdAsync",
    "GetRuntimeByIdAsync",
    "GetRuntimeHealthByIdAsync",
    "StartRuntimeByIdAsync",
    "StopRuntimeByIdAsync",
    "RestartRuntimeByIdAsync",
    "ListRuntimeInstancesByIdAsync",
    "GetRuntimeEventsByIdAsync",
    "CheckRuntimeFlowByIdAsync",
    "InvokeRuntimeAppResultByIdAsync",
    "InvokeRuntimeAppResultWithImageBase64ByIdAsync",
    "InvokeRuntimeAppResultWithImageBytesByIdAsync",
    "InvokeRuntimeAppResultWithImageFromFileByIdAsync",
    "RunRuntimeByIdAsync",
    "RunRuntimeWithImageBase64ByIdAsync",
    "RunRuntimeWithImageBytesByIdAsync",
    "RunRuntimeWithImageFromFileByIdAsync",
    "GetWorkflowRunEventsByRuntimeIdAsync",
    "GetModelDeploymentRuntimeStatusByIdAsync",
    "GetModelDeploymentRuntimeHealthByIdAsync",
    "StartModelDeploymentRuntimeByIdAsync",
    "StopModelDeploymentRuntimeByIdAsync",
    "ResetModelDeploymentRuntimeByIdAsync",
    "WarmupModelDeploymentRuntimeByIdAsync",
    "InvokeConfiguredModelDeploymentByIdAsync",
    "InvokeModelDeploymentWithImageBase64ByIdAsync",
    "InvokeModelDeploymentWithImageBytesByIdAsync",
    "InvokeModelDeploymentWithImageFromFileByIdAsync",
    "InvokeModelDeploymentWithInputFileIdByIdAsync",
    "InvokeModelDeploymentWithInputUriByIdAsync",
    "RunConfiguredModelDeploymentByIdAsync",
    "RunModelDeploymentWithImageBase64ByIdAsync",
    "RunModelDeploymentWithImageBytesByIdAsync",
    "RunModelDeploymentWithImageFromFileByIdAsync",
    "RunModelDeploymentWithInputFileIdByIdAsync",
    "RunModelDeploymentWithInputUriByIdAsync",
    "GetModelInferenceTaskByIdAsync",
    "GetModelInferenceTaskResultByIdAsync",
    "ListTriggerSourcesByRuntimeIdAsync",
    "GetTriggerSourceByIdAsync",
    "EnableTriggerSourceByIdAsync",
    "DisableTriggerSourceByIdAsync",
    "GetTriggerSourceHealthByIdAsync",
    "InvokeZeroMqEventById",
    "InvokeConfiguredZeroMqImageById",
    "InvokeZeroMqImageFromFileById",
    "InvokeZeroMqImageBytesById",
    "InvokeZeroMqImageBase64ById",
    "InvokeZeroMqBgr24ById",
    "InvokeZeroMqBgr24FromBitmapById",
    "InvokeZeroMqBgr24FromFileById",
    "InvokeConfiguredZeroMqBgr24ImageById",
}


def test_dotnet_runner_exposes_and_console_lists_all_by_id_methods() -> None:
    """每个约定的 id 方法都必须存在，并出现在第三方参考 Console 中。"""

    selector_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in SDK_ROOT.glob("AMVisionOperationRunner.*Id.cs")
    )
    selector_text += (SDK_ROOT / "AMVisionOperationRunner.Selectors.cs").read_text(
        encoding="utf-8"
    )
    method_names = set(
        re.findall(r"public\s+(?:Task<[^\r\n]+>|TriggerResult)\s+(\w+)\s*\(", selector_text)
    )
    assert EXPECTED_BY_ID_METHODS <= method_names

    console_text = CONSOLE_ID_CALLS.read_text(encoding="utf-8")
    missing_examples = sorted(
        method_name for method_name in EXPECTED_BY_ID_METHODS if f".{method_name}(" not in console_text
    )
    assert missing_examples == []


def test_console_separates_name_and_id_examples_in_operation_order() -> None:
    """Program 直接切换两个入口，两个文件都按模型、runtime、trigger 顺序组织。"""

    program_text = CONSOLE_PROGRAM.read_text(encoding="utf-8")
    assert "KeyNameSdkCalls.RunAsync(" in program_text
    assert "ResourceIdSdkCalls.RunAsync(" in program_text

    for path in (CONSOLE_NAME_CALLS, CONSOLE_ID_CALLS):
        text = path.read_text(encoding="utf-8")
        model_index = text.index("RunModelDeploymentCallsAsync")
        runtime_index = text.index("RunWorkflowRuntimeCallsAsync")
        trigger_index = text.index("RunTriggerSourceCallsAsync")
        assert model_index < runtime_index < trigger_index


def test_config_catalog_uses_prebuilt_exact_id_indexes() -> None:
    """id 兜底入口必须使用启动时索引，并在加载时拒绝重复 id。"""

    catalog_text = (SDK_ROOT / "Model" / "WorkflowConfigurationCatalog.cs").read_text(
        encoding="utf-8"
    )
    assert "runtimesById.TryGetValue" in catalog_text
    assert "triggerSourcesById.TryGetValue" in catalog_text
    assert "modelDeploymentsByIdAndMode.TryGetValue" in catalog_text
    assert "Duplicate {fieldName} in SDK config catalog" in catalog_text


def test_config_loader_rejects_mixed_http_backends() -> None:
    """一个长期复用的 Runner 不能把不同 HTTP backend 配置静默合并。"""

    loader_text = (SDK_ROOT / "Tools" / "WorkflowConfigLoader.cs").read_text(
        encoding="utf-8"
    )
    assert "HttpBackendsEquivalent" in loader_text
    assert "All config files loaded by one SDK runner must use the same" in loader_text


def test_runner_model_runtime_commands_return_typed_responses() -> None:
    """模型管理的后端正常数据仍应保持明确的强类型。"""

    runner_text = (SDK_ROOT / "AMVisionOperationRunner.cs").read_text(encoding="utf-8")
    id_text = (SDK_ROOT / "AMVisionOperationRunner.ModelId.cs").read_text(encoding="utf-8")
    for method_name in ("Start", "Stop"):
        assert (
            f"Task<ModelDeploymentRuntimeStatusResponse> {method_name}ModelDeploymentRuntimeAsync"
            in runner_text
        )
        assert (
            f"Task<ModelDeploymentRuntimeStatusResponse> {method_name}ModelDeploymentRuntimeByIdAsync"
            in id_text
        )
    for method_name in ("Reset", "Warmup"):
        assert (
            f"Task<ModelDeploymentRuntimeHealthResponse> {method_name}ModelDeploymentRuntimeAsync"
            in runner_text
        )
        assert (
            f"Task<ModelDeploymentRuntimeHealthResponse> {method_name}ModelDeploymentRuntimeByIdAsync"
            in id_text
        )


def test_console_uses_non_throwing_call_boundary_and_real_config_key() -> None:
    """Console 的每次调用都应返回结果对象，示例 deployment key 必须来自 Config。"""

    name_calls = CONSOLE_NAME_CALLS.read_text(encoding="utf-8")
    id_calls = CONSOLE_ID_CALLS.read_text(encoding="utf-8")
    assert "runner.CallAsync(api =>" in name_calls
    assert "runner.Call(api =>" in name_calls
    assert "runner.CallAsync(api =>" in id_calls
    assert "runner.Call(api =>" in id_calls

    match = re.search(r'ModelDeploymentName = "([^"]+)"', name_calls)
    assert match is not None
    configured_names: set[str] = set()
    for config_path in (SDK_ROOT / "Config").glob("config*.json"):
        payload = json.loads(config_path.read_text(encoding="utf-8"))
        configured_names.update(
            item["name"] for item in payload.get("model_deployments", [])
        )
    assert match.group(1) in configured_names


def test_call_result_preserves_data_http_response_or_exception() -> None:
    """调用边界只保留原始事实，不替第三方判断成功或失败。"""

    result_text = (SDK_ROOT / "Http" / "AMVisionCallResult.cs").read_text(
        encoding="utf-8"
    )
    boundary_text = (
        SDK_ROOT / "AMVisionOperationRunner.CallResults.cs"
    ).read_text(encoding="utf-8")
    assert "public T Data" in result_text
    assert "public AMVisionApiResponse? HttpResponse" in result_text
    assert "public Exception? Exception" in result_text
    assert "catch (AMVisionApiException exception)" in boundary_text
    assert "catch (Exception exception)" in boundary_text


def test_dotnet_http_timeout_defaults_and_generated_configs_are_300_seconds() -> None:
    """配置生成器、SDK 默认值和已提交示例配置统一使用 300 秒。"""

    backend_config = (SDK_ROOT / "Model" / "BackendConfig.cs").read_text(encoding="utf-8")
    client_options = (SDK_ROOT / "Http" / "AMVisionClientOptions.cs").read_text(encoding="utf-8")
    assert "HttpTimeoutSeconds { get; set; } = 300;" in backend_config
    assert "Timeout { get; set; } = TimeSpan.FromSeconds(300);" in client_options

    for config_path in (SDK_ROOT / "Config").glob("config*.json"):
        payload = json.loads(config_path.read_text(encoding="utf-8"))
        assert payload["backend"]["http_timeout_seconds"] == 300


def test_netmq_runtime_dependencies_are_packaged() -> None:
    """ZeroMQ 完整传递依赖必须进入离线库并由 SDK 项目复制到输出目录。"""

    dependency_names = (
        "System.Runtime.CompilerServices.Unsafe.dll",
        "System.Memory.dll",
        "System.Buffers.dll",
        "System.Numerics.Vectors.dll",
    )
    project_text = (
        SDK_ROOT / "Amvar.Vision.vs2019.net472.csproj"
    ).read_text(encoding="utf-8")
    readme_text = (ROOT / "sdks" / "dotnet" / "README.md").read_text(encoding="utf-8")

    for dependency_name in dependency_names:
        dependency_path = (
            ROOT / "sdks" / "dotnet" / "libs" / "net472" / dependency_name
        )
        assert dependency_path.is_file()
        assert dependency_path.stat().st_size > 0
        assert f"libs\\net472\\{dependency_name}" in project_text
    assert "<Private>true</Private>" in project_text
    assert "AssemblyVersion 6.0.3.0" in readme_text
    assert "AssemblyVersion 4.0.5.0" in readme_text


def test_dotnet_runtime_contract_exposes_version_revision_and_provenance() -> None:
    """控制面 SDK 必须跟随 Runtime 版本接口，调用配置仍只保存稳定 id。"""

    request_text = (
        SDK_ROOT / "Http" / "Requests" / "WorkflowAppRuntimeCreateRequest.cs"
    ).read_text(encoding="utf-8")
    select_text = (
        SDK_ROOT
        / "Http"
        / "Requests"
        / "WorkflowAppRuntimeSelectVersionRequest.cs"
    ).read_text(encoding="utf-8")
    runtime_response_text = (
        SDK_ROOT / "Http" / "Responses" / "WorkflowAppRuntimeResponse.cs"
    ).read_text(encoding="utf-8")
    run_response_text = (
        SDK_ROOT / "Http" / "Responses" / "WorkflowRunResponse.cs"
    ).read_text(encoding="utf-8")
    client_text = (SDK_ROOT / "Http" / "AMVisionClient.Runtime.cs").read_text(
        encoding="utf-8"
    )
    harness_project_text = (
        ROOT
        / "sdks"
        / "dotnet"
        / "tests"
        / "Amvar.Vision.ContractTests"
        / "Amvar.Vision.ContractTests.vs2019.net472.csproj"
    ).read_text(encoding="utf-8")

    assert 'JsonProperty("workflow_app_version_id")' in request_text
    assert 'JsonProperty("expected_generation")' in select_text
    assert 'JsonProperty("active_revision_id")' in runtime_response_text
    assert 'JsonProperty("desired_revision_id")' in runtime_response_text
    assert 'JsonProperty("revision_generation")' in runtime_response_text
    assert 'JsonProperty("worker_instance_id")' in runtime_response_text
    assert 'JsonProperty("loaded_snapshot_fingerprint")' in runtime_response_text
    assert "WorkflowRuntimeRevisionResponse" in runtime_response_text
    assert 'JsonProperty("workflow_runtime_revision_id")' in run_response_text
    assert 'JsonProperty("workflow_app_version_id")' in run_response_text
    assert 'JsonProperty("runtime_generation")' in run_response_text
    assert 'JsonProperty("snapshot_fingerprint")' in run_response_text
    assert 'JsonProperty("worker_instance_id")' in run_response_text
    assert "SelectWorkflowAppRuntimeVersionResponseAsync" in client_text
    assert "ListWorkflowRuntimeRevisionResponsesAsync" in client_text
    assert '<Project ToolsVersion="15.0"' in harness_project_text
    assert "<TargetFrameworkVersion>v4.7.2</TargetFrameworkVersion>" in harness_project_text
    assert "PackageReference" not in harness_project_text


@pytest.mark.skipif(
    os.name != "nt",
    reason="net472 可执行契约测试需要 Windows .NET Framework 运行时",
)
def test_dotnet_workflow_version_json_contracts_compile_and_run() -> None:
    """真实编译 SDK，并验证版本请求、响应和 409 details 的 JSON 行为。"""

    dotnet = shutil.which("dotnet")
    if dotnet is None:
        pytest.skip("未安装 dotnet/MSBuild，无法编译 net472 SDK 契约测试")

    project = (
        ROOT
        / "sdks"
        / "dotnet"
        / "tests"
        / "Amvar.Vision.ContractTests"
        / "Amvar.Vision.ContractTests.vs2019.net472.csproj"
    )
    build = subprocess.run(
        [
            dotnet,
            "msbuild",
            str(project),
            "/t:Rebuild",
            "/p:Configuration=Release",
            "/p:TreatWarningsAsErrors=true",
            "/v:minimal",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        check=False,
    )
    assert build.returncode == 0, build.stdout + build.stderr

    executable = (
        project.parent
        / "bin"
        / "Release"
        / "net472"
        / "Amvar.Vision.ContractTests.exe"
    )
    run = subprocess.run(
        [str(executable)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
        check=False,
    )
    assert run.returncode == 0, run.stdout + run.stderr
    assert "Workflow App version JSON contracts passed." in run.stdout
