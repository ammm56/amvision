using System;
using System.Collections.Generic;
using Newtonsoft.Json;

namespace Amvar.Vision
{

    /// <summary>
    /// WorkflowAppRuntime 创建请求。
    /// </summary>
    public sealed class WorkflowAppRuntimeCreateRequest
    {
        [JsonProperty("project_id")]
        public string ProjectId { get; set; } = string.Empty;

        [JsonProperty("application_id")]
        public string? ApplicationId { get; set; }

        [JsonProperty("workflow_app_version_id")]
        public string? WorkflowAppVersionId { get; set; }

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

        /// <summary>
        /// 校验 Runtime 来源必须在旧 application 和不可变发布版本之间二选一。
        /// </summary>
        internal void ValidateVersionSelector()
        {
            var hasApplicationId = !string.IsNullOrWhiteSpace(ApplicationId);
            var hasWorkflowAppVersionId = !string.IsNullOrWhiteSpace(WorkflowAppVersionId);
            if (hasApplicationId == hasWorkflowAppVersionId)
            {
                throw new ArgumentException(
                    "ApplicationId and WorkflowAppVersionId must contain exactly one value.");
            }
        }
    }
}
