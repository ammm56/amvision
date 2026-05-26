using System.Collections.Generic;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace Amvision.TriggerSources;

/// <summary>
/// ZeroMQ TriggerSource adapter 返回的错误 reply。
/// </summary>
public sealed class ZeroMqTriggerError
{
    /// <summary>
    /// ZeroMQ 错误 reply format_id。
    /// </summary>
    [JsonPropertyName("format_id")]
    public string FormatId { get; set; } = string.Empty;

    /// <summary>
    /// 错误所属的 TriggerSource id。
    /// </summary>
    [JsonPropertyName("trigger_source_id")]
    public string TriggerSourceId { get; set; } = string.Empty;

    /// <summary>
    /// 错误 reply 状态。
    /// </summary>
    [JsonPropertyName("state")]
    public string State { get; set; } = string.Empty;

    /// <summary>
    /// backend-service 返回的错误码。
    /// </summary>
    [JsonPropertyName("error_code")]
    public string ErrorCode { get; set; } = string.Empty;

    /// <summary>
    /// backend-service 返回的错误消息。
    /// </summary>
    [JsonPropertyName("error_message")]
    public string ErrorMessage { get; set; } = string.Empty;

    /// <summary>
    /// backend-service 返回的错误详情。
    /// </summary>
    [JsonPropertyName("details")]
    public Dictionary<string, JsonElement> Details { get; set; } = new Dictionary<string, JsonElement>();
}