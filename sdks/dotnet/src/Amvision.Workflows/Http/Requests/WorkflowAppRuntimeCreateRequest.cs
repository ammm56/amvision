using System.Collections.Generic;
using Newtonsoft.Json;

namespace Amvision.Workflows
{

    /// <summary>
    /// WorkflowAppRuntime 创建请求。
    /// </summary>
    public sealed class WorkflowAppRuntimeCreateRequest
    {
        [JsonProperty("project_id")]
        public string ProjectId { get; set; } = string.Empty;

        [JsonProperty("application_id")]
        public string ApplicationId { get; set; } = string.Empty;

        [JsonProperty("execution_policy_id")]
        public string? ExecutionPolicyId { get; set; }

        [JsonProperty("display_name")]
        public string DisplayName { get; set; } = string.Empty;

        [JsonProperty("request_timeout_seconds")]
        public int? RequestTimeoutSeconds { get; set; }

        [JsonProperty("heartbeat_interval_seconds")]
        public int? HeartbeatIntervalSeconds { get; set; }

        [JsonProperty("heartbeat_timeout_seconds")]
        public int? HeartbeatTimeoutSeconds { get; set; }

        [JsonProperty("metadata")]
        public IDictionary<string, object?> Metadata { get; } = new Dictionary<string, object?>();
    }
}
