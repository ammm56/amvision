using System;
using System.Collections.Generic;
using Newtonsoft.Json.Linq;
using Newtonsoft.Json;
namespace Amvar.Vision
{

    /// <summary>
    /// backend-service 返回的 Workflow trigger result。
    /// </summary>
    public sealed class TriggerResult
    {
        /// <summary>
        /// TriggerResult format_id。
        /// </summary>
        [JsonProperty("format_id")]
        public string FormatId { get; set; } = string.Empty;

        /// <summary>
        /// 返回结果所属的 TriggerSource id。
        /// </summary>
        [JsonProperty("trigger_source_id")]
        public string TriggerSourceId { get; set; } = string.Empty;

        /// <summary>
        /// 对应的 trigger event id。
        /// </summary>
        [JsonProperty("event_id")]
        public string EventId { get; set; } = string.Empty;

        /// <summary>
        /// 触发结果状态。
        /// </summary>
        [JsonProperty("state")]
        public string State { get; set; } = string.Empty;

        /// <summary>
        /// 已创建或已执行的 WorkflowRun id。
        /// </summary>
        [JsonProperty("workflow_run_id")]
        public string? WorkflowRunId { get; set; }

        /// <summary>
        /// workflow 返回的协议中立响应 payload。
        /// </summary>
        [JsonProperty("response_payload")]
        public Dictionary<string, JToken> ResponsePayload { get; set; } = new Dictionary<string, JToken>();

        /// <summary>
        /// 失败时的错误消息。
        /// </summary>
        [JsonProperty("error_message")]
        public string? ErrorMessage { get; set; }

        /// <summary>
        /// backend-service 返回的附加元数据。
        /// </summary>
        [JsonProperty("metadata")]
        public Dictionary<string, JToken> Metadata { get; set; } = new Dictionary<string, JToken>();

        /// <summary>
        /// ZeroMQ multipart reply 中已经复制到 SDK 自有 byte[] 的逻辑图片结果。
        /// 同一物理帧被多个 binding 引用时，各 attachment 共享同一个 byte[] 实例。
        /// </summary>
        [JsonIgnore]
        public IReadOnlyList<TriggerImageAttachment> ImageAttachments { get; internal set; }
            = Array.Empty<TriggerImageAttachment>();
    }

    /// <summary>
    /// TriggerResult 中一个有序逻辑图片输出。
    /// </summary>
    public sealed class TriggerImageAttachment
    {
        public string AttachmentId { get; internal set; } = string.Empty;
        public string BindingId { get; internal set; } = string.Empty;
        public int ItemIndex { get; internal set; }
        public string PayloadId { get; internal set; } = string.Empty;
        public string MediaType { get; internal set; } = string.Empty;
        public byte[] Content { get; internal set; } = Array.Empty<byte>();
        public int? Width { get; internal set; }
        public int? Height { get; internal set; }
        public IReadOnlyList<int> Shape { get; internal set; } = Array.Empty<int>();
        public string? DType { get; internal set; }
        public string? Layout { get; internal set; }
        public string? PixelFormat { get; internal set; }
    }
}
