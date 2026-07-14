using System.Collections.Generic;
using System.Text.Json.Serialization;

namespace Amvision.Workflows
{

    /// <summary>
    /// WorkflowAppRuntime 创建请求。
    /// </summary>
    public sealed class WorkflowAppRuntimeCreateRequest
    {
        [JsonPropertyName("project_id")]
        public string ProjectId { get; set; } = string.Empty;

        [JsonPropertyName("application_id")]
        public string ApplicationId { get; set; } = string.Empty;

        [JsonPropertyName("execution_policy_id")]
        public string? ExecutionPolicyId { get; set; }

        [JsonPropertyName("display_name")]
        public string DisplayName { get; set; } = string.Empty;

        [JsonPropertyName("request_timeout_seconds")]
        public int? RequestTimeoutSeconds { get; set; }

        [JsonPropertyName("heartbeat_interval_seconds")]
        public int? HeartbeatIntervalSeconds { get; set; }

        [JsonPropertyName("heartbeat_timeout_seconds")]
        public int? HeartbeatTimeoutSeconds { get; set; }

        [JsonPropertyName("metadata")]
        public IDictionary<string, object?> Metadata { get; } = new Dictionary<string, object?>();
    }
}
