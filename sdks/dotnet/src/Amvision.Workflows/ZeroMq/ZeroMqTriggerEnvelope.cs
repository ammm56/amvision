using System.Collections.Generic;
using Newtonsoft.Json;

namespace Amvision.Workflows
{

    /// <summary>
    /// ZeroMQ multipart 第一帧 envelope。
    /// </summary>
    public sealed class ZeroMqTriggerEnvelope
    {
        /// <summary>
        /// 目标 TriggerSource id。
        /// </summary>
        [JsonProperty("trigger_source_id")]
        public string? TriggerSourceId { get; set; }

        /// <summary>
        /// 本次触发事件 id。
        /// </summary>
        [JsonProperty("event_id")]
        public string? EventId { get; set; }

        /// <summary>
        /// 链路追踪 id。
        /// </summary>
        [JsonProperty("trace_id")]
        public string? TraceId { get; set; }

        /// <summary>
        /// 事件发生时间。
        /// </summary>
        [JsonProperty("occurred_at")]
        public string? OccurredAt { get; set; }

        /// <summary>
        /// 图片 payload 写入的 input binding 名称。
        /// </summary>
        [JsonProperty("input_binding")]
        public string? InputBinding { get; set; }

        /// <summary>
        /// 图片或 raw frame 的 media type。
        /// </summary>
        [JsonProperty("media_type")]
        public string? MediaType { get; set; }

        /// <summary>
        /// raw image shape，例如 [height, width, channels]。
        /// </summary>
        [JsonProperty("shape")]
        public IReadOnlyList<int>? Shape { get; set; }

        /// <summary>
        /// raw dtype，例如 uint8。
        /// </summary>
        [JsonProperty("dtype")]
        public string? DType { get; set; }

        /// <summary>
        /// raw layout，例如 HWC。
        /// </summary>
        [JsonProperty("layout")]
        public string? Layout { get; set; }

        /// <summary>
        /// pixel format，例如 BGR 或 RGB。
        /// </summary>
        [JsonProperty("pixel_format")]
        public string? PixelFormat { get; set; }

        /// <summary>
        /// envelope metadata 对象。
        /// </summary>
        [JsonProperty("metadata")]
        public IDictionary<string, object?> Metadata { get; set; } = new Dictionary<string, object?>();

        /// <summary>
        /// envelope payload 对象。
        /// </summary>
        [JsonProperty("payload")]
        public IDictionary<string, object?> Payload { get; set; } = new Dictionary<string, object?>();
    }
}
