using System.Collections.Generic;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace Amvision.TriggerSources;

/// <summary>
/// backend-service 返回的 Workflow trigger result。
/// </summary>
public sealed class TriggerResult
{
    /// <summary>
    /// TriggerResult format_id。
    /// </summary>
    [JsonPropertyName("format_id")]
    public string FormatId { get; set; } = string.Empty;

    /// <summary>
    /// 返回结果所属的 TriggerSource id。
    /// </summary>
    [JsonPropertyName("trigger_source_id")]
    public string TriggerSourceId { get; set; } = string.Empty;

    /// <summary>
    /// 对应的 trigger event id。
    /// </summary>
    [JsonPropertyName("event_id")]
    public string EventId { get; set; } = string.Empty;

    /// <summary>
    /// 触发结果状态。
    /// </summary>
    [JsonPropertyName("state")]
    public string State { get; set; } = string.Empty;

    /// <summary>
    /// 已创建或已执行的 WorkflowRun id。
    /// </summary>
    [JsonPropertyName("workflow_run_id")]
    public string? WorkflowRunId { get; set; }

    /// <summary>
    /// workflow 返回的协议中立响应 payload。
    /// </summary>
    [JsonPropertyName("response_payload")]
    public Dictionary<string, JsonElement> ResponsePayload { get; set; } = new Dictionary<string, JsonElement>();

    /// <summary>
    /// 失败时的错误消息。
    /// </summary>
    [JsonPropertyName("error_message")]
    public string? ErrorMessage { get; set; }

    /// <summary>
    /// backend-service 返回的附加元数据。
    /// </summary>
    [JsonPropertyName("metadata")]
    public Dictionary<string, JsonElement> Metadata { get; set; } = new Dictionary<string, JsonElement>();
}