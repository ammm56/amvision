using System.Collections.Generic;
using Newtonsoft.Json.Linq;
using Newtonsoft.Json;

namespace Amvision.Workflows
{

    /// <summary>
    /// WorkflowAppRuntime 响应模型。
    /// </summary>
    public sealed class WorkflowAppRuntimeResponse
    {
        [JsonProperty("format_id")]
        public string FormatId { get; set; } = string.Empty;

        [JsonProperty("workflow_runtime_id")]
        public string WorkflowRuntimeId { get; set; } = string.Empty;

        [JsonProperty("project_id")]
        public string ProjectId { get; set; } = string.Empty;

        [JsonProperty("application_id")]
        public string ApplicationId { get; set; } = string.Empty;

        [JsonProperty("execution_policy_id")]
        public string? ExecutionPolicyId { get; set; }

        [JsonProperty("display_name")]
        public string DisplayName { get; set; } = string.Empty;

        [JsonProperty("desired_state")]
        public string DesiredState { get; set; } = string.Empty;

        [JsonProperty("observed_state")]
        public string ObservedState { get; set; } = string.Empty;

        [JsonProperty("worker_process_id")]
        public int? WorkerProcessId { get; set; }

        [JsonProperty("last_started_at")]
        public string? LastStartedAt { get; set; }

        [JsonProperty("last_stopped_at")]
        public string? LastStoppedAt { get; set; }

        [JsonProperty("heartbeat_at")]
        public string? HeartbeatAt { get; set; }

        [JsonProperty("last_error")]
        public JToken? LastError { get; set; }

        [JsonProperty("health_summary")]
        public IDictionary<string, JToken> HealthSummary { get; set; } = new Dictionary<string, JToken>();

        [JsonProperty("metadata")]
        public IDictionary<string, JToken> Metadata { get; set; } = new Dictionary<string, JToken>();

        [JsonProperty("created_at")]
        public string CreatedAt { get; set; } = string.Empty;

        [JsonProperty("updated_at")]
        public string UpdatedAt { get; set; } = string.Empty;
    }

    /// <summary>
    /// WorkflowAppRuntime 事件响应模型。
    /// </summary>
    public sealed class WorkflowAppRuntimeEventResponse
    {
        [JsonProperty("format_id")]
        public string FormatId { get; set; } = string.Empty;

        [JsonProperty("workflow_runtime_id")]
        public string WorkflowRuntimeId { get; set; } = string.Empty;

        [JsonProperty("sequence")]
        public long Sequence { get; set; }

        [JsonProperty("event_type")]
        public string EventType { get; set; } = string.Empty;

        [JsonProperty("occurred_at")]
        public string OccurredAt { get; set; } = string.Empty;

        [JsonProperty("payload")]
        public IDictionary<string, JToken> Payload { get; set; } = new Dictionary<string, JToken>();
    }

    /// <summary>
    /// WorkflowAppRuntime worker instance 响应模型。
    /// </summary>
    public sealed class WorkflowAppRuntimeInstanceResponse
    {
        [JsonProperty("format_id")]
        public string FormatId { get; set; } = string.Empty;

        [JsonProperty("workflow_runtime_id")]
        public string WorkflowRuntimeId { get; set; } = string.Empty;

        [JsonProperty("instance_id")]
        public string InstanceId { get; set; } = string.Empty;

        [JsonProperty("state")]
        public string State { get; set; } = string.Empty;

        [JsonProperty("process_id")]
        public int? ProcessId { get; set; }

        [JsonProperty("health_summary")]
        public IDictionary<string, JToken> HealthSummary { get; set; } = new Dictionary<string, JToken>();
    }
}
