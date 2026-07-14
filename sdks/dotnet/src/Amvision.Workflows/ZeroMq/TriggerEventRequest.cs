using System;
using System.Collections.Generic;

namespace Amvision.Workflows
{

    /// <summary>
    /// 发送纯事件到 ZeroMQ TriggerSource 的请求。
    /// </summary>
    public sealed class TriggerEventRequest
    {
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
        /// 写入 envelope metadata 对象的业务元数据。
        /// </summary>
        public IDictionary<string, object?> Metadata { get; } = new Dictionary<string, object?>();

        /// <summary>
        /// 写入 envelope payload 对象的业务字段。
        /// </summary>
        public IDictionary<string, object?> Payload { get; } = new Dictionary<string, object?>();

        /// <summary>
        /// 创建空 payload 纯事件触发请求。
        /// </summary>
        public static TriggerEventRequest Empty()
        {
            return new TriggerEventRequest();
        }

        /// <summary>
        /// 从 payload 创建纯事件触发请求。
        /// </summary>
        public static TriggerEventRequest FromPayload(IDictionary<string, object?> payload)
        {
            if (payload is null)
            {
                throw new ArgumentNullException(nameof(payload));
            }

            var request = new TriggerEventRequest();
            foreach (var item in payload)
            {
                request.Payload[item.Key] = item.Value;
            }

            return request;
        }

        /// <summary>
        /// 添加 payload 字段。
        /// </summary>
        public TriggerEventRequest WithPayload(string name, object? value)
        {
            if (string.IsNullOrWhiteSpace(name))
            {
                throw new ArgumentException("name cannot be empty.", nameof(name));
            }

            Payload[name.Trim()] = value;
            return this;
        }

        /// <summary>
        /// 添加 metadata 字段。
        /// </summary>
        public TriggerEventRequest WithMetadata(string name, object? value)
        {
            if (string.IsNullOrWhiteSpace(name))
            {
                throw new ArgumentException("name cannot be empty.", nameof(name));
            }

            Metadata[name.Trim()] = value;
            return this;
        }

        /// <summary>
        /// 设置幂等键，并默认写入 payload.idempotency_key。
        /// </summary>
        public TriggerEventRequest WithIdempotencyKey(string idempotencyKey)
        {
            if (string.IsNullOrWhiteSpace(idempotencyKey))
            {
                throw new ArgumentException("idempotencyKey cannot be empty.", nameof(idempotencyKey));
            }

            IdempotencyKey = idempotencyKey.Trim();
            return this;
        }
    }
}
