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
    }
}
