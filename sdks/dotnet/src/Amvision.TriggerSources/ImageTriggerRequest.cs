using System;
using System.Collections.Generic;

namespace Amvision.TriggerSources;

/// <summary>
/// 发送单张图片到 ZeroMQ TriggerSource 的请求。
/// </summary>
public sealed class ImageTriggerRequest
{
    /// <summary>
    /// 作为 multipart 第二帧发送的图片 bytes。
    /// </summary>
    public byte[] ImageBytes { get; set; } = Array.Empty<byte>();

    /// <summary>
    /// MIME media type，例如 image/jpeg。
    /// </summary>
    public string MediaType { get; set; } = "image/octet-stream";

    /// <summary>
    /// 可选 event id；为空时由 SDK 生成。
    /// </summary>
    public string? EventId { get; set; }

    /// <summary>
    /// 可选 trace id；为空时由 SDK 生成。
    /// </summary>
    public string? TraceId { get; set; }

    /// <summary>
    /// 可选事件发生时间；为空时使用当前 UTC 时间。
    /// </summary>
    public DateTimeOffset? OccurredAt { get; set; }

    /// <summary>
    /// 可选 input binding；为空时使用客户端默认值。
    /// </summary>
    public string? InputBinding { get; set; }

    /// <summary>
    /// 可选 raw image shape，例如 [height, width, channels]。
    /// </summary>
    public IReadOnlyList<int> Shape { get; set; } = Array.Empty<int>();

    /// <summary>
    /// 可选 raw dtype，例如 uint8。
    /// </summary>
    public string? DType { get; set; }

    /// <summary>
    /// 可选 raw layout，例如 HWC。
    /// </summary>
    public string? Layout { get; set; }

    /// <summary>
    /// 可选 pixel format，例如 BGR 或 RGB。
    /// </summary>
    public string? PixelFormat { get; set; }

    /// <summary>
    /// 写入 envelope metadata 对象的业务元数据。
    /// </summary>
    public IDictionary<string, object?> Metadata { get; } = new Dictionary<string, object?>();

    /// <summary>
    /// 写入 envelope payload 对象的附加业务字段。
    /// </summary>
    public IDictionary<string, object?> Payload { get; } = new Dictionary<string, object?>();
}