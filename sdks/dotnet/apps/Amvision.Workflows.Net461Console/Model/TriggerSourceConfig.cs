using System;
using System.Collections.Generic;
using System.Text.Json.Serialization;

namespace Amvision.Workflows.Net461Console.Model;

/// <summary>
/// TriggerSource 管理和协议调用配置，对应 trigger_sources[] 节点。
/// </summary>
internal sealed class TriggerSourceConfig
{
    /// <summary>
    /// 本程序内部使用的 TriggerSource 字典 key。
    /// </summary>
    [JsonPropertyName("name")]
    public string Name { get; set; } = string.Empty;

    /// <summary>
    /// 后端持久化的 WorkflowTriggerSource id。
    /// </summary>
    [JsonPropertyName("trigger_source_id")]
    public string TriggerSourceId { get; set; } = string.Empty;

    /// <summary>
    /// 前端和后端展示用名称。
    /// </summary>
    [JsonPropertyName("display_name")]
    public string DisplayName { get; set; } = string.Empty;

    /// <summary>
    /// TriggerSource 类型，例如 zeromq-topic。
    /// </summary>
    [JsonPropertyName("trigger_kind")]
    public string TriggerKind { get; set; } = "zeromq-topic";

    /// <summary>
    /// 关联的 runtime key；为空时默认使用同一配置文件中的 runtime。
    /// </summary>
    [JsonPropertyName("workflow_runtime_name")]
    public string? WorkflowRuntimeName { get; set; }

    /// <summary>
    /// 触发后提交 WorkflowRun 的模式，例如 sync。
    /// </summary>
    [JsonPropertyName("submit_mode")]
    public string SubmitMode { get; set; } = "sync";

    /// <summary>
    /// 创建 TriggerSource 后是否立即启用。
    /// </summary>
    [JsonPropertyName("enabled")]
    public bool Enabled { get; set; }

    /// <summary>
    /// TriggerSource acknowledge 策略。
    /// </summary>
    [JsonPropertyName("ack_policy")]
    public string AckPolicy { get; set; } = "ack-after-run-finished";

    /// <summary>
    /// 触发结果返回模式，例如 sync-reply。
    /// </summary>
    [JsonPropertyName("result_mode")]
    public string ResultMode { get; set; } = "sync-reply";

    /// <summary>
    /// workflow app 输出 binding 名称。
    /// </summary>
    [JsonPropertyName("result_binding")]
    public string ResultBinding { get; set; } = "workflow_result";

    /// <summary>
    /// 等待触发结果返回的超时时间，单位为秒。
    /// </summary>
    [JsonPropertyName("reply_timeout_seconds")]
    public int? ReplyTimeoutSeconds { get; set; }

    /// <summary>
    /// 防抖窗口，单位为毫秒；为空时不启用防抖。
    /// </summary>
    [JsonPropertyName("debounce_window_ms")]
    public int? DebounceWindowMs { get; set; }

    /// <summary>
    /// 幂等键读取路径，例如 payload.request_id。
    /// </summary>
    [JsonPropertyName("idempotency_key_path")]
    public string? IdempotencyKeyPath { get; set; }

    /// <summary>
    /// ZeroMQ transport 和调用配置。
    /// </summary>
    [JsonPropertyName("zero_mq")]
    public TriggerSourceZeroMqConfig ZeroMq { get; set; } = new TriggerSourceZeroMqConfig();

    /// <summary>
    /// TriggerSource 事件字段到 workflow input binding 的映射。
    /// </summary>
    [JsonPropertyName("input_binding_mapping")]
    public Dictionary<string, TriggerInputBindingConfig> InputBindingMapping { get; set; } =
        new Dictionary<string, TriggerInputBindingConfig>();

    /// <summary>
    /// TriggerSource 结果返回 mapping。
    /// </summary>
    [JsonPropertyName("result_mapping")]
    public TriggerResultMappingConfig ResultMapping { get; set; } = new TriggerResultMappingConfig();

    /// <summary>
    /// 可选事件匹配规则，当前 ZeroMQ 场景通常为空。
    /// </summary>
    [JsonPropertyName("match_rule")]
    public Dictionary<string, object?> MatchRule { get; set; } = new Dictionary<string, object?>();

    /// <summary>
    /// TriggerSource 创建后写入每次执行的默认 execution metadata。
    /// </summary>
    [JsonPropertyName("default_execution_metadata")]
    public Dictionary<string, object?> DefaultExecutionMetadata { get; set; } = new Dictionary<string, object?>();

    /// <summary>
    /// TriggerSource 记录自身的附加 metadata。
    /// </summary>
    [JsonPropertyName("metadata")]
    public Dictionary<string, object?> Metadata { get; set; } = new Dictionary<string, object?>();

    /// <summary>
    /// 校验 TriggerSource 配置并补齐默认 runtime 关联。
    /// </summary>
    /// <param name="path">配置字段路径。</param>
    /// <param name="runtimeName">同一配置文件中的 runtime key。</param>
    public void Validate(string path, string runtimeName)
    {
        Name = ConfigValidation.RequireText(Name, $"{path}.name");
        TriggerSourceId = ConfigValidation.RequireText(TriggerSourceId, $"{path}.trigger_source_id");
        TriggerKind = ConfigValidation.RequireText(TriggerKind, $"{path}.trigger_kind");
        SubmitMode = ConfigValidation.RequireText(SubmitMode, $"{path}.submit_mode");
        AckPolicy = ConfigValidation.RequireText(AckPolicy, $"{path}.ack_policy");
        ResultMode = ConfigValidation.RequireText(ResultMode, $"{path}.result_mode");
        ResultBinding = ConfigValidation.RequireText(ResultBinding, $"{path}.result_binding");
        DisplayName = string.IsNullOrWhiteSpace(DisplayName) ? Name : DisplayName.Trim();
        WorkflowRuntimeName = ConfigValidation.NormalizeOptional(WorkflowRuntimeName) ?? runtimeName;
        ZeroMq.Validate($"{path}.zero_mq");
        if (ReplyTimeoutSeconds is <= 0)
        {
            throw new InvalidOperationException($"{path}.reply_timeout_seconds must be greater than zero.");
        }

        if (DebounceWindowMs is <= 0)
        {
            throw new InvalidOperationException($"{path}.debounce_window_ms must be greater than zero.");
        }
    }
}
