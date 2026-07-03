using System;
using System.Text.Json.Serialization;

namespace Amvision.Workflows.Net461Console.Model;

/// <summary>
/// 已存在 WorkflowAppRuntime 的调用和生命周期控制配置。
/// </summary>
internal sealed class WorkflowRuntimeConfig
{
    /// <summary>
    /// 本程序内部使用的 runtime 字典 key。
    /// </summary>
    [JsonPropertyName("name")]
    public string Name { get; set; } = string.Empty;

    /// <summary>
    /// 前端已创建的 WorkflowAppRuntime id。
    /// </summary>
    [JsonPropertyName("workflow_runtime_id")]
    public string WorkflowRuntimeId { get; set; } = string.Empty;

    /// <summary>
    /// 校验 runtime 配置是否指向一个已存在的后端 runtime。
    /// </summary>
    /// <param name="path">配置字段路径。</param>
    public void Validate(string path)
    {
        Name = ConfigValidation.RequireText(Name, $"{path}.name");
        WorkflowRuntimeId = ConfigValidation.RequireText(WorkflowRuntimeId, $"{path}.workflow_runtime_id");
    }
}
