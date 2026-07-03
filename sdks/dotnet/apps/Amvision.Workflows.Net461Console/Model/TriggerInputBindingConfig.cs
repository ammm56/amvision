using System.Collections.Generic;
using System.Text.Json.Serialization;

namespace Amvision.Workflows.Net461Console.Model;

/// <summary>
/// TriggerSource 事件字段到 workflow input binding 的映射配置。
/// </summary>
internal sealed class TriggerInputBindingConfig
{
    /// <summary>
    /// 从 TriggerSource event context 读取值的 dotted path，例如 payload.request_image_ref。
    /// </summary>
    [JsonPropertyName("source")]
    public string? Source { get; set; }

    /// <summary>
    /// 固定值映射；当 source 为空时可直接写入 workflow input binding。
    /// </summary>
    [JsonPropertyName("value")]
    public object? Value { get; set; }

    /// <summary>
    /// 该 input binding 是否必填。
    /// </summary>
    [JsonPropertyName("required")]
    public bool Required { get; set; } = true;

    /// <summary>
    /// input payload 类型 id，例如 image-ref.v1。
    /// </summary>
    [JsonPropertyName("payload_type_id")]
    public string? PayloadTypeId { get; set; }

    /// <summary>
    /// 传给后端 TriggerSource mapping 的附加元数据。
    /// </summary>
    [JsonPropertyName("metadata")]
    public Dictionary<string, object?> Metadata { get; set; } = new Dictionary<string, object?>();
}
