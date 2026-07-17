"""验证 .NET SDK name/id 入口和 Console 示例保持完整。"""

from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SDK_ROOT = ROOT / "sdks" / "dotnet" / "src" / "Amvar.Vision"
CONSOLE_PROGRAM = ROOT / "sdks" / "dotnet" / "apps" / "AMVision.Console" / "Program.cs"

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

    console_text = CONSOLE_PROGRAM.read_text(encoding="utf-8")
    missing_examples = sorted(
        method_name for method_name in EXPECTED_BY_ID_METHODS if f".{method_name}(" not in console_text
    )
    assert missing_examples == []


def test_dotnet_http_timeout_defaults_and_generated_configs_are_300_seconds() -> None:
    """配置生成器、SDK 默认值和已提交示例配置统一使用 300 秒。"""

    backend_config = (SDK_ROOT / "Model" / "BackendConfig.cs").read_text(encoding="utf-8")
    client_options = (SDK_ROOT / "Http" / "AMVisionClientOptions.cs").read_text(encoding="utf-8")
    assert "HttpTimeoutSeconds { get; set; } = 300;" in backend_config
    assert "Timeout { get; set; } = TimeSpan.FromSeconds(300);" in client_options

    for config_path in (SDK_ROOT / "Config").glob("config*.json"):
        payload = json.loads(config_path.read_text(encoding="utf-8"))
        assert payload["backend"]["http_timeout_seconds"] == 300
