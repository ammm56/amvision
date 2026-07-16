using System;
using System.Collections.Generic;
using System.Globalization;
using System.Text;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using System.Threading;
using System.Threading.Tasks;

namespace Amvar.Vision
{

    /// <summary>
    /// 用于向 Amvar Vision ZeroMQ TriggerSource 发送事件或图片的客户端。
    /// </summary>
    public sealed class AMVisionTriggerClient : IDisposable
    {
        /// <summary>
        /// backend-service 返回的 TriggerResult format_id。
        /// </summary>
        public const string TriggerResultFormatId = "amvision.workflow-trigger-result.v1";

        /// <summary>
        /// ZeroMQ adapter 返回的错误 reply format_id。
        /// </summary>
        public const string ZeroMqErrorFormatId = "amvision.zeromq-trigger-error.v1";

        /// <summary>
        /// 保护底层 transport 调用和释放；ZeroMQ REQ/REP 调用必须一问一答串行执行。
        /// </summary>
        private readonly object syncRoot = new object();
        private readonly AMVisionTriggerClientOptions options;
        private readonly IZeroMqRequestTransport transport;
        private readonly bool ownsTransport;
        private bool disposed;

        /// <summary>
        /// 使用 NetMQ transport 初始化 TriggerSource 客户端。
        /// </summary>
        /// <param name="options">客户端连接和默认 TriggerSource 参数。</param>
        public AMVisionTriggerClient(AMVisionTriggerClientOptions options)
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
        public AMVisionTriggerClient(AMVisionTriggerClientOptions options, IZeroMqRequestTransport transport)
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
            ValidateRequest(request);
            var envelope = BuildEnvelope(request);
            var envelopeBytes = WorkflowJsonDefaults.SerializeToUtf8Bytes(envelope);
            var requestFrames = new[] { envelopeBytes, request.ImageBytes };
            IReadOnlyList<byte[]> replyFrames;
            try
            {
                lock (syncRoot)
                {
                    ThrowIfDisposed();
                    replyFrames = transport.Send(requestFrames, options.Timeout);
                }
            }
            catch (AMVisionTriggerException)
            {
                throw;
            }
            catch (ObjectDisposedException)
            {
                throw;
            }
            catch (Exception exception)
            {
                throw CreateTransportException("image", exception);
            }

            var result = ParseReply(replyFrames);
            return result;
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
            var task = Task.Run(
                () =>
                {
                    var result = InvokeImage(request);
                    return result;
                },
                cancellationToken);
            return task;
        }

        /// <summary>
        /// 同步发送一条纯事件并解析 TriggerResult。
        /// </summary>
        /// <param name="request">纯事件触发请求。</param>
        /// <returns>backend-service 返回的 TriggerResult。</returns>
        public TriggerResult InvokeEvent(TriggerEventRequest request)
        {
            ValidateRequest(request);
            var envelope = BuildEnvelope(request);
            var envelopeBytes = WorkflowJsonDefaults.SerializeToUtf8Bytes(envelope);
            var requestFrames = new[] { envelopeBytes };
            IReadOnlyList<byte[]> replyFrames;
            try
            {
                lock (syncRoot)
                {
                    ThrowIfDisposed();
                    replyFrames = transport.Send(requestFrames, options.Timeout);
                }
            }
            catch (AMVisionTriggerException)
            {
                throw;
            }
            catch (ObjectDisposedException)
            {
                throw;
            }
            catch (Exception exception)
            {
                throw CreateTransportException("event", exception);
            }

            var result = ParseReply(replyFrames);
            return result;
        }

        /// <summary>
        /// 在线程池中异步执行纯事件触发。
        /// </summary>
        /// <param name="request">纯事件触发请求。</param>
        /// <param name="cancellationToken">调用前的取消令牌。</param>
        /// <returns>异步 TriggerResult 任务。</returns>
        public Task<TriggerResult> InvokeEventAsync(TriggerEventRequest request, CancellationToken cancellationToken = default)
        {
            cancellationToken.ThrowIfCancellationRequested();
            var task = Task.Run(
                () =>
                {
                    var result = InvokeEvent(request);
                    return result;
                },
                cancellationToken);
            return task;
        }

        /// <summary>
        /// 根据图片请求和客户端默认值构造 ZeroMQ envelope。
        /// </summary>
        /// <param name="request">单张图片触发请求。</param>
        /// <returns>可序列化为 multipart 第一帧的 envelope。</returns>
        public ZeroMqTriggerEnvelope BuildEnvelope(ImageTriggerRequest request)
        {
            ValidateRequest(request);

            var envelope = new ZeroMqTriggerEnvelope
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
                Payload = BuildPayload(request.Payload, request.IdempotencyKey)
            };
            return envelope;
        }

        /// <summary>
        /// 根据纯事件请求和客户端默认值构造 ZeroMQ envelope。
        /// </summary>
        /// <param name="request">纯事件触发请求。</param>
        /// <returns>可序列化为 multipart 第一帧的 envelope。</returns>
        public ZeroMqTriggerEnvelope BuildEnvelope(TriggerEventRequest request)
        {
            ValidateRequest(request);
            var envelope = new ZeroMqTriggerEnvelope
            {
                TriggerSourceId = options.TriggerSourceId,
                EventId = NormalizeOptional(request.EventId) ?? $"trigger-event-{Guid.NewGuid():N}",
                TraceId = NormalizeOptional(request.TraceId) ?? $"trace-{Guid.NewGuid():N}",
                OccurredAt = FormatUtc(request.OccurredAt ?? DateTimeOffset.UtcNow),
                Metadata = new Dictionary<string, object?>(request.Metadata),
                Payload = BuildPayload(request.Payload, request.IdempotencyKey)
            };
            return envelope;
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
                throw new AMVisionTriggerException("invalid_reply", "ZeroMQ TriggerSource reply is empty.");
            }

            var json = Encoding.UTF8.GetString(replyFrames[0]);
            JObject root;
            try
            {
                root = JObject.Parse(json);
            }
            catch (JsonException exception)
            {
                throw new AMVisionTriggerException(
                    "invalid_reply",
                    "ZeroMQ TriggerSource reply is not valid JSON.",
                    null,
                    exception);
            }

            var formatId = root.Value<string>("format_id");

            if (formatId == ZeroMqErrorFormatId || root["error_code"] != null)
            {
                var error = WorkflowJsonDefaults.Deserialize<ZeroMqTriggerError>(json);
                throw new AMVisionTriggerException(
                    error?.ErrorCode ?? "trigger_error",
                    error?.ErrorMessage ?? "ZeroMQ TriggerSource returned an error.",
                    error?.Details
                );
            }

            var result = WorkflowJsonDefaults.Deserialize<TriggerResult>(json);
            if (result is null)
            {
                throw new AMVisionTriggerException("invalid_reply", "ZeroMQ TriggerSource reply cannot be parsed.");
            }

            if (result.FormatId != TriggerResultFormatId)
            {
                throw new AMVisionTriggerException(
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
            lock (syncRoot)
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
        }

        /// <summary>
        /// 检查客户端是否已经释放。
        /// </summary>
        private void ThrowIfDisposed()
        {
            if (disposed)
            {
                throw new ObjectDisposedException(nameof(AMVisionTriggerClient));
            }
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

            if (string.Equals(request.MediaType?.Trim(), ImageTriggerRequest.RawImageMediaType, StringComparison.OrdinalIgnoreCase))
            {
                ValidateRawBgr24Request(request);
            }
        }

        /// <summary>
        /// 校验 raw BGR24 图片触发请求。
        /// </summary>
        /// <param name="request">待校验的图片请求。</param>
        private static void ValidateRawBgr24Request(ImageTriggerRequest request)
        {
            if (request.Shape.Count != 3 || request.Shape[2] != 3)
            {
                throw new ArgumentException("Raw BGR24 image requires Shape=[height,width,3].", nameof(request));
            }

            if (!string.Equals(NormalizeOptional(request.DType), "uint8", StringComparison.OrdinalIgnoreCase))
            {
                throw new ArgumentException("Raw BGR24 image requires DType=uint8.", nameof(request));
            }

            if (!string.Equals(NormalizeOptional(request.Layout), "HWC", StringComparison.OrdinalIgnoreCase))
            {
                throw new ArgumentException("Raw BGR24 image requires Layout=HWC.", nameof(request));
            }

            var pixelFormat = NormalizeOptional(request.PixelFormat)?.Replace("-", string.Empty).Replace("_", string.Empty);
            if (!string.Equals(pixelFormat, "bgr24", StringComparison.OrdinalIgnoreCase)
                && !string.Equals(pixelFormat, "bgr", StringComparison.OrdinalIgnoreCase))
            {
                throw new ArgumentException("Raw BGR24 image requires PixelFormat=bgr24.", nameof(request));
            }

            var expectedLength = checked(request.Shape[0] * request.Shape[1] * request.Shape[2]);
            if (request.ImageBytes.Length != expectedLength)
            {
                throw new ArgumentException($"Raw BGR24 ImageBytes length must be width * height * 3. Expected {expectedLength}, actual {request.ImageBytes.Length}.", nameof(request));
            }
        }

        /// <summary>
        /// 校验纯事件触发请求的基础字段。
        /// </summary>
        /// <param name="request">待校验的请求。</param>
        private static void ValidateRequest(TriggerEventRequest request)
        {
            if (request is null)
            {
                throw new ArgumentNullException(nameof(request));
            }
        }

        /// <summary>
        /// 构造 envelope payload，并按约定补充幂等键。
        /// </summary>
        /// <param name="sourcePayload">业务 payload。</param>
        /// <param name="idempotencyKey">可选幂等键。</param>
        /// <returns>最终 payload。</returns>
        private static Dictionary<string, object?> BuildPayload(
            IDictionary<string, object?> sourcePayload,
            string? idempotencyKey)
        {
            var payload = new Dictionary<string, object?>(sourcePayload);
            var normalizedIdempotencyKey = NormalizeOptional(idempotencyKey);
            if (normalizedIdempotencyKey != null
                && !payload.ContainsKey("idempotency_key"))
            {
                payload["idempotency_key"] = normalizedIdempotencyKey;
            }

            return payload;
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
            if (normalized.Length == 0)
            {
                return null;
            }

            return normalized;
        }

        /// <summary>
        /// 把时间转换为 UTC ISO-like 字符串。
        /// </summary>
        /// <param name="value">待格式化的时间。</param>
        /// <returns>UTC 时间字符串。</returns>
        private static string FormatUtc(DateTimeOffset value)
        {
            var utcValue = value.ToUniversalTime();
            var formatted = utcValue.ToString("yyyy-MM-dd'T'HH:mm:ss.fffffff'Z'", CultureInfo.InvariantCulture);
            return formatted;
        }

        /// <summary>
        /// 把底层 ZeroMQ transport 异常包装成 SDK 可识别的异常。
        /// </summary>
        /// <param name="payloadKind">触发 payload 类型。</param>
        /// <param name="exception">底层异常。</param>
        /// <returns>包含调用上下文的 TriggerSource 异常。</returns>
        private AMVisionTriggerException CreateTransportException(string payloadKind, Exception exception)
        {
            var details = new Dictionary<string, JToken>
            {
                ["endpoint"] = JToken.FromObject(options.Endpoint ?? string.Empty),
                ["trigger_source_id"] = JToken.FromObject(options.TriggerSourceId ?? string.Empty),
                ["payload_kind"] = JToken.FromObject(payloadKind),
                ["exception_type"] = JToken.FromObject(exception.GetType().FullName ?? exception.GetType().Name)
            };

            var triggerException = new AMVisionTriggerException(
                "transport_error",
                "ZeroMQ TriggerSource call failed.",
                details,
                exception);
            return triggerException;
        }
    }
}
