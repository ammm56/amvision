using System.Collections.Generic;
using System.Text.Json.Serialization;

namespace Amvision.Workflows.Net461Console.Model;

/// <summary>
/// TriggerSource 同步返回结果的 mapping 配置。
/// </summary>
internal sealed class TriggerResultMappingConfig
{
    /// <summary>
    /// workflow app 输出 binding 名称。
    /// </summary>
    [JsonPropertyName("result_binding")]
    public string ResultBinding { get; set; } = "workflow_result";

    /// <summary>
    /// 结果返回模式，例如 sync-reply。
    /// </summary>
    [JsonPropertyName("result_mode")]
    public string ResultMode { get; set; } = "sync-reply";

    /// <summary>
    /// 等待同步返回的超时时间，单位为秒。
    /// </summary>
    [JsonPropertyName("reply_timeout_seconds")]
    public int? ReplyTimeoutSeconds { get; set; }

    /// <summary>
    /// 传给 result mapping 的附加元数据。
    /// </summary>
    [JsonPropertyName("metadata")]
    public Dictionary<string, object?> Metadata { get; set; } = new Dictionary<string, object?>();
}
