using System;
using System.Collections.Generic;
using System.Globalization;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;
using System.Threading;
using System.Threading.Tasks;

namespace Amvision.TriggerSources;

/// <summary>
/// 用于向 Amvision ZeroMQ TriggerSource 发送图片的客户端。
/// </summary>
public sealed class AmvisionTriggerClient : IDisposable
{
    /// <summary>
    /// backend-service 返回的 TriggerResult format_id。
    /// </summary>
    public const string TriggerResultFormatId = "amvision.workflow-trigger-result.v1";

    /// <summary>
    /// ZeroMQ adapter 返回的错误 reply format_id。
    /// </summary>
    public const string ZeroMqErrorFormatId = "amvision.zeromq-trigger-error.v1";

    private static readonly JsonSerializerOptions JsonOptions = new JsonSerializerOptions
    {
        DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull,
        PropertyNamingPolicy = null,
        WriteIndented = false
    };

    private readonly AmvisionTriggerClientOptions options;
    private readonly IZeroMqRequestTransport transport;
    private readonly bool ownsTransport;
    private bool disposed;

    /// <summary>
    /// 使用 NetMQ transport 初始化 TriggerSource 客户端。
    /// </summary>
    /// <param name="options">客户端连接和默认 TriggerSource 参数。</param>
    public AmvisionTriggerClient(AmvisionTriggerClientOptions options)
    {
        this.options = options ?? throw new ArgumentNullException(nameof(options));
        this.options.Validate(requireEndpoint: true);
        transport = new NetMqRequestTransport(options.Endpoint);
        ownsTransport = true;
    }

    /// <summary>
    /// 使用自定义 ZeroMQ request transport 初始化 TriggerSource 客户端。
    /// </summary>
    /// <param name="options">客户端连接和默认 TriggerSource 参数。</param>
    /// <param name="transport">用于测试或自定义通信的 transport。</param>
    public AmvisionTriggerClient(AmvisionTriggerClientOptions options, IZeroMqRequestTransport transport)
    {
        this.options = options ?? throw new ArgumentNullException(nameof(options));
        this.options.Validate(requireEndpoint: false);
        this.transport = transport ?? throw new ArgumentNullException(nameof(transport));
        ownsTransport = false;
    }

    /// <summary>
    /// 同步发送一张图片并解析 TriggerResult。
    /// </summary>
    /// <param name="request">单张图片触发请求。</param>
    /// <returns>backend-service 返回的 TriggerResult。</returns>
    public TriggerResult InvokeImage(ImageTriggerRequest request)
    {
        if (disposed)
        {
            throw new ObjectDisposedException(nameof(AmvisionTriggerClient));
        }

        ValidateRequest(request);
        var envelope = BuildEnvelope(request);
        var envelopeBytes = JsonSerializer.SerializeToUtf8Bytes(envelope, JsonOptions);
        var replyFrames = transport.Send(
            new[] { envelopeBytes, request.ImageBytes },
            options.Timeout
        );
        return ParseReply(replyFrames);
    }

    /// <summary>
    /// 在线程池中异步执行单张图片触发。
    /// </summary>
    /// <param name="request">单张图片触发请求。</param>
    /// <param name="cancellationToken">调用前的取消令牌。</param>
    /// <returns>异步 TriggerResult 任务。</returns>
    public Task<TriggerResult> InvokeImageAsync(ImageTriggerRequest request, CancellationToken cancellationToken = default)
    {
        cancellationToken.ThrowIfCancellationRequested();
        return Task.Run(() => InvokeImage(request), cancellationToken);
    }

    /// <summary>
    /// 根据图片请求和客户端默认值构造 ZeroMQ envelope。
    /// </summary>
    /// <param name="request">单张图片触发请求。</param>
    /// <returns>可序列化为 multipart 第一帧的 envelope。</returns>
    public ZeroMqTriggerEnvelope BuildEnvelope(ImageTriggerRequest request)
    {
        ValidateRequest(request);
        return new ZeroMqTriggerEnvelope
        {
            TriggerSourceId = options.TriggerSourceId,
            EventId = NormalizeOptional(request.EventId) ?? $"trigger-event-{Guid.NewGuid():N}",
            TraceId = NormalizeOptional(request.TraceId) ?? $"trace-{Guid.NewGuid():N}",
            OccurredAt = FormatUtc(request.OccurredAt ?? DateTimeOffset.UtcNow),
            InputBinding = NormalizeOptional(request.InputBinding) ?? options.DefaultInputBinding,
            MediaType = NormalizeOptional(request.MediaType) ?? "image/octet-stream",
            Shape = new List<int>(request.Shape),
            DType = NormalizeOptional(request.DType),
            Layout = NormalizeOptional(request.Layout),
            PixelFormat = NormalizeOptional(request.PixelFormat),
            Metadata = new Dictionary<string, object?>(request.Metadata),
            Payload = new Dictionary<string, object?>(request.Payload)
        };
    }

    /// <summary>
    /// 解析 ZeroMQ reply 帧并转换为 TriggerResult 或 SDK 异常。
    /// </summary>
    /// <param name="replyFrames">ZeroMQ REP 返回的 multipart 帧。</param>
    /// <returns>解析后的 TriggerResult。</returns>
    public static TriggerResult ParseReply(IReadOnlyList<byte[]> replyFrames)
    {
        if (replyFrames.Count == 0)
        {
            throw new AmvisionTriggerException("invalid_reply", "ZeroMQ TriggerSource reply is empty.");
        }

        var json = Encoding.UTF8.GetString(replyFrames[0]);
        using var document = JsonDocument.Parse(json);
        var root = document.RootElement;
        var formatId = root.TryGetProperty("format_id", out var formatProperty)
            ? formatProperty.GetString()
            : null;

        if (formatId == ZeroMqErrorFormatId || root.TryGetProperty("error_code", out _))
        {
            var error = JsonSerializer.Deserialize<ZeroMqTriggerError>(json, JsonOptions);
            throw new AmvisionTriggerException(
                error?.ErrorCode ?? "trigger_error",
                error?.ErrorMessage ?? "ZeroMQ TriggerSource returned an error.",
                error?.Details
            );
        }

        var result = JsonSerializer.Deserialize<TriggerResult>(json, JsonOptions);
        if (result is null)
        {
            throw new AmvisionTriggerException("invalid_reply", "ZeroMQ TriggerSource reply cannot be parsed.");
        }

        if (result.FormatId != TriggerResultFormatId)
        {
            throw new AmvisionTriggerException(
                "invalid_reply",
                $"Unexpected TriggerResult format_id: {result.FormatId}."
            );
        }

        return result;
    }

    /// <summary>
    /// 释放当前客户端持有的 transport。
    /// </summary>
    public void Dispose()
    {
        if (disposed)
        {
            return;
        }

        if (ownsTransport)
        {
            transport.Dispose();
        }

        disposed = true;
    }

    /// <summary>
    /// 校验图片触发请求的基础字段。
    /// </summary>
    /// <param name="request">待校验的请求。</param>
    private static void ValidateRequest(ImageTriggerRequest request)
    {
        if (request is null)
        {
            throw new ArgumentNullException(nameof(request));
        }

        if (request.ImageBytes is null || request.ImageBytes.Length == 0)
        {
            throw new ArgumentException("ImageBytes cannot be empty.", nameof(request));
        }

        foreach (var dimension in request.Shape)
        {
            if (dimension <= 0)
            {
                throw new ArgumentException("Shape dimensions must be positive.", nameof(request));
            }
        }
    }

    /// <summary>
    /// 规范化可选字符串，空白字符串返回 null。
    /// </summary>
    /// <param name="value">待规范化的字符串。</param>
    /// <returns>规范化后的字符串或 null。</returns>
    private static string? NormalizeOptional(string? value)
    {
        if (value is null)
        {
            return null;
        }

        var normalized = value.Trim();
        return normalized.Length == 0 ? null : normalized;
    }

    /// <summary>
    /// 把时间转换为 UTC ISO-like 字符串。
    /// </summary>
    /// <param name="value">待格式化的时间。</param>
    /// <returns>UTC 时间字符串。</returns>
    private static string FormatUtc(DateTimeOffset value)
    {
        return value.ToUniversalTime().ToString("yyyy-MM-dd'T'HH:mm:ss.fffffff'Z'", CultureInfo.InvariantCulture);
    }
}