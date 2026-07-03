using System;
using System.Text.Json.Serialization;

namespace Amvision.Workflows.Net461Console.Model;

/// <summary>
/// WorkflowAppRuntime 创建、复用和生命周期控制配置。
/// </summary>
internal sealed class WorkflowRuntimeConfig
{
    /// <summary>
    /// 本程序内部使用的 runtime 字典 key。
    /// </summary>
    [JsonPropertyName("name")]
    public string Name { get; set; } = string.Empty;

    /// <summary>
    /// 已存在的 WorkflowAppRuntime id；为空时可根据 application_id 创建新 runtime。
    /// </summary>
    [JsonPropertyName("workflow_runtime_id")]
    public string? WorkflowRuntimeId { get; set; }

    /// <summary>
    /// 用于创建 runtime 的 WorkflowApp id。
    /// </summary>
    [JsonPropertyName("application_id")]
    public string? ApplicationId { get; set; }

    /// <summary>
    /// 可选执行策略 id。
    /// </summary>
    [JsonPropertyName("execution_policy_id")]
    public string? ExecutionPolicyId { get; set; }

    /// <summary>
    /// runtime 展示名称。
    /// </summary>
    [JsonPropertyName("display_name")]
    public string DisplayName { get; set; } = string.Empty;

    /// <summary>
    /// 单次请求执行超时时间，单位为秒。
    /// </summary>
    [JsonPropertyName("request_timeout_seconds")]
    public int RequestTimeoutSeconds { get; set; } = 30;

    /// <summary>
    /// runtime heartbeat 上报间隔，单位为秒。
    /// </summary>
    [JsonPropertyName("heartbeat_interval_seconds")]
    public int HeartbeatIntervalSeconds { get; set; } = 5;

    /// <summary>
    /// runtime heartbeat 判定超时时间，单位为秒。
    /// </summary>
    [JsonPropertyName("heartbeat_timeout_seconds")]
    public int HeartbeatTimeoutSeconds { get; set; } = 15;

    /// <summary>
    /// 完整 runtime-run 流程中是否执行重启验证。
    /// </summary>
    [JsonPropertyName("restart_runtime")]
    public bool RestartRuntime { get; set; }

    /// <summary>
    /// 校验 runtime 配置是否能复用已有 runtime 或创建新 runtime。
    /// </summary>
    /// <param name="path">配置字段路径。</param>
    public void Validate(string path)
    {
        Name = ConfigValidation.RequireText(Name, $"{path}.name");
        DisplayName = string.IsNullOrWhiteSpace(DisplayName) ? Name : DisplayName.Trim();
        WorkflowRuntimeId = ConfigValidation.NormalizeOptional(WorkflowRuntimeId);
        ApplicationId = ConfigValidation.NormalizeOptional(ApplicationId);
        ExecutionPolicyId = ConfigValidation.NormalizeOptional(ExecutionPolicyId);
        if (WorkflowRuntimeId is null && ApplicationId is null)
        {
            throw new InvalidOperationException($"{path}.workflow_runtime_id or {path}.application_id must be set.");
        }

        if (RequestTimeoutSeconds <= 0)
        {
            throw new InvalidOperationException($"{path}.request_timeout_seconds must be greater than zero.");
        }

        if (HeartbeatIntervalSeconds <= 0)
        {
            throw new InvalidOperationException($"{path}.heartbeat_interval_seconds must be greater than zero.");
        }

        if (HeartbeatTimeoutSeconds <= 0)
        {
            throw new InvalidOperationException($"{path}.heartbeat_timeout_seconds must be greater than zero.");
        }
    }
}
