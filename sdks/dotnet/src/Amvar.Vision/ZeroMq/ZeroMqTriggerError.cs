using System.Collections.Generic;
using Newtonsoft.Json.Linq;
using Newtonsoft.Json;
namespace Amvar.Vision
{

    /// <summary>
    /// ZeroMQ TriggerSource adapter 返回的错误 reply。
    /// </summary>
    public sealed class ZeroMqTriggerError
    {
        /// <summary>
        /// ZeroMQ 错误 reply format_id。
        /// </summary>
        [JsonProperty("format_id")]
        public string FormatId { get; set; } = string.Empty;

        /// <summary>
        /// 错误所属的 TriggerSource id。
        /// </summary>
        [JsonProperty("trigger_source_id")]
        public string TriggerSourceId { get; set; } = string.Empty;

        /// <summary>
        /// 错误 reply 状态。
        /// </summary>
        [JsonProperty("state")]
        public string State { get; set; } = string.Empty;

        /// <summary>
        /// backend-service 返回的错误码。
        /// </summary>
        [JsonProperty("error_code")]
        public string ErrorCode { get; set; } = string.Empty;

        /// <summary>
        /// backend-service 返回的错误消息。
        /// </summary>
        [JsonProperty("error_message")]
        public string ErrorMessage { get; set; } = string.Empty;

        /// <summary>
        /// backend-service 返回的错误详情。
        /// </summary>
        [JsonProperty("details")]
        public Dictionary<string, JToken> Details { get; set; } = new Dictionary<string, JToken>();
    }
}
