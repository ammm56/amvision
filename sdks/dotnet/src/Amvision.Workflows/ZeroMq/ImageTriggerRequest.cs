using System;
using System.Collections.Generic;
using System.IO;

namespace Amvision.Workflows;

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
    /// 可选幂等键；默认写入 payload.idempotency_key。
    /// </summary>
    public string? IdempotencyKey { get; set; }

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

    /// <summary>
    /// 从已有图片 bytes 创建 ZeroMQ 图片触发请求；bytes 会作为 multipart 第二帧发送。
    /// </summary>
    /// <param name="imageBytes">图片 bytes，通常是 JPEG/PNG 编码后的内容。</param>
    /// <param name="mediaType">MIME media type，例如 image/jpeg。</param>
    /// <returns>图片触发请求。</returns>
    public static ImageTriggerRequest FromBytes(byte[] imageBytes, string mediaType = "image/octet-stream")
    {
        if (imageBytes is null || imageBytes.Length == 0)
        {
            throw new ArgumentException("imageBytes cannot be empty.", nameof(imageBytes));
        }

        return new ImageTriggerRequest
        {
            ImageBytes = imageBytes,
            MediaType = NormalizeMediaType(mediaType)
        };
    }

    /// <summary>
    /// 从文件读取图片 bytes 创建 ZeroMQ 图片触发请求；文件内容会作为 multipart 第二帧发送。
    /// </summary>
    /// <param name="filePath">本机图片文件路径。</param>
    /// <param name="mediaType">可选 MIME media type；为空时按扩展名推断。</param>
    /// <returns>图片触发请求。</returns>
    public static ImageTriggerRequest FromFile(string filePath, string? mediaType = null)
    {
        if (string.IsNullOrWhiteSpace(filePath))
        {
            throw new ArgumentException("filePath cannot be empty.", nameof(filePath));
        }

        var normalizedPath = filePath.Trim();
        return FromBytes(File.ReadAllBytes(normalizedPath), mediaType ?? InferMediaType(normalizedPath));
    }

    /// <summary>
    /// 从 base64 或 data URL 创建 ZeroMQ 图片触发请求；SDK 会先解码为 bytes，再作为 multipart 第二帧发送。
    /// </summary>
    /// <param name="imageBase64">纯 base64 字符串，或 data:image/...;base64,...。</param>
    /// <param name="mediaType">可选 MIME media type；data URL 会优先使用自身声明。</param>
    /// <returns>图片触发请求。</returns>
    public static ImageTriggerRequest FromBase64(string imageBase64, string? mediaType = null)
    {
        if (string.IsNullOrWhiteSpace(imageBase64))
        {
            throw new ArgumentException("imageBase64 cannot be empty.", nameof(imageBase64));
        }

        var normalizedBase64 = imageBase64.Trim();
        var resolvedMediaType = mediaType;
        var commaIndex = normalizedBase64.IndexOf(',');
        if (normalizedBase64.StartsWith("data:", StringComparison.OrdinalIgnoreCase) && commaIndex > 0)
        {
            var header = normalizedBase64.Substring(5, commaIndex - 5);
            var separatorIndex = header.IndexOf(';');
            var headerMediaType = separatorIndex >= 0 ? header.Substring(0, separatorIndex) : header;
            if (!string.IsNullOrWhiteSpace(headerMediaType))
            {
                resolvedMediaType = headerMediaType.Trim();
            }
            normalizedBase64 = normalizedBase64.Substring(commaIndex + 1);
        }

        return FromBytes(Convert.FromBase64String(normalizedBase64), resolvedMediaType ?? "image/octet-stream");
    }

    /// <summary>
    /// 从 stream 读取图片 bytes 创建 ZeroMQ 图片触发请求；读取结果会作为 multipart 第二帧发送。
    /// </summary>
    /// <param name="stream">包含图片编码数据的 stream。</param>
    /// <param name="mediaType">MIME media type，例如 image/jpeg。</param>
    /// <returns>图片触发请求。</returns>
    public static ImageTriggerRequest FromStream(Stream stream, string mediaType = "image/octet-stream")
    {
        if (stream is null)
        {
            throw new ArgumentNullException(nameof(stream));
        }

        using var memoryStream = new MemoryStream();
        stream.CopyTo(memoryStream);
        return FromBytes(memoryStream.ToArray(), mediaType);
    }

    /// <summary>
    /// 写入 deployment_request.value.deployment_instance_id。
    /// </summary>
    /// <param name="deploymentInstanceId">部署实例 id。</param>
    /// <returns>当前请求对象。</returns>
    public ImageTriggerRequest WithDeploymentInstance(string deploymentInstanceId)
    {
        if (string.IsNullOrWhiteSpace(deploymentInstanceId))
        {
            throw new ArgumentException("deploymentInstanceId cannot be empty.", nameof(deploymentInstanceId));
        }

        Payload["deployment_request"] = new Dictionary<string, object?>
        {
            ["value"] = new Dictionary<string, object?>
            {
                ["deployment_instance_id"] = deploymentInstanceId.Trim()
            }
        };
        return this;
    }

    /// <summary>
    /// 设置幂等键，并默认写入 payload.idempotency_key。
    /// </summary>
    /// <param name="idempotencyKey">幂等键。</param>
    /// <returns>当前请求对象。</returns>
    public ImageTriggerRequest WithIdempotencyKey(string idempotencyKey)
    {
        if (string.IsNullOrWhiteSpace(idempotencyKey))
        {
            throw new ArgumentException("idempotencyKey cannot be empty.", nameof(idempotencyKey));
        }

        IdempotencyKey = idempotencyKey.Trim();
        return this;
    }

    private static string NormalizeMediaType(string mediaType)
    {
        return string.IsNullOrWhiteSpace(mediaType) ? "image/octet-stream" : mediaType.Trim();
    }

    private static string InferMediaType(string filePath)
    {
        var extension = Path.GetExtension(filePath).ToLowerInvariant();
        return extension switch
        {
            ".jpg" or ".jpeg" => "image/jpeg",
            ".png" => "image/png",
            ".bmp" => "image/bmp",
            ".webp" => "image/webp",
            ".tif" or ".tiff" => "image/tiff",
            _ => "image/octet-stream"
        };
    }
}
