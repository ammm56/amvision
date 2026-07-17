"""验证 .NET SDK name/id 入口和 Console 示例保持完整。"""

from __future__ import annotations

import json
import re
from pathlib import Path


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
