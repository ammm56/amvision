using System.Collections.Generic;
using System.Text.Json.Serialization;

namespace Amvision.TriggerSources;

/// <summary>
/// ZeroMQ multipart 第一帧 envelope。
/// </summary>
public sealed class ZeroMqTriggerEnvelope
{
    /// <summary>
    /// 目标 TriggerSource id。
    /// </summary>
    [JsonPropertyName("trigger_source_id")]
    public string? TriggerSourceId { get; set; }

    /// <summary>
    /// 本次触发事件 id。
    /// </summary>
    [JsonPropertyName("event_id")]
    public string? EventId { get; set; }

    /// <summary>
    /// 链路追踪 id。
    /// </summary>
    [JsonPropertyName("trace_id")]
    public string? TraceId { get; set; }

    /// <summary>
    /// 事件发生时间。
    /// </summary>
    [JsonPropertyName("occurred_at")]
    public string? OccurredAt { get; set; }

    /// <summary>
    /// 图片 payload 写入的 input binding 名称。
    /// </summary>
    [JsonPropertyName("input_binding")]
    public string? InputBinding { get; set; }

    /// <summary>
    /// 图片或 raw frame 的 media type。
    /// </summary>
    [JsonPropertyName("media_type")]
    public string? MediaType { get; set; }

    /// <summary>
    /// raw image shape，例如 [height, width, channels]。
    /// </summary>
    [JsonPropertyName("shape")]
    public IReadOnlyList<int> Shape { get; set; } = new List<int>();

    /// <summary>
    /// raw dtype，例如 uint8。
    /// </summary>
    [JsonPropertyName("dtype")]
    public string? DType { get; set; }

    /// <summary>
    /// raw layout，例如 HWC。
    /// </summary>
    [JsonPropertyName("layout")]
    public string? Layout { get; set; }

    /// <summary>
    /// pixel format，例如 BGR 或 RGB。
    /// </summary>
    [JsonPropertyName("pixel_format")]
    public string? PixelFormat { get; set; }

    /// <summary>
    /// envelope metadata 对象。
    /// </summary>
    [JsonPropertyName("metadata")]
    public IDictionary<string, object?> Metadata { get; set; } = new Dictionary<string, object?>();

    /// <summary>
    /// envelope payload 对象。
    /// </summary>
    [JsonPropertyName("payload")]
    public IDictionary<string, object?> Payload { get; set; } = new Dictionary<string, object?>();
}