using System.Collections.Generic;
using Newtonsoft.Json.Linq;
using Newtonsoft.Json;

namespace Amvar.Vision
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

        [JsonProperty("application_snapshot_object_key")]
        public string ApplicationSnapshotObjectKey { get; set; } = string.Empty;

        [JsonProperty("template_snapshot_object_key")]
        public string TemplateSnapshotObjectKey { get; set; } = string.Empty;

        [JsonProperty("execution_policy_snapshot_object_key")]
        public string? ExecutionPolicySnapshotObjectKey { get; set; }

        [JsonProperty("active_revision_id")]
        public string? ActiveRevisionId { get; set; }

        [JsonProperty("desired_revision_id")]
        public string? DesiredRevisionId { get; set; }

        [JsonProperty("revision_generation")]
        public int RevisionGeneration { get; set; }

        [JsonProperty("display_name")]
        public string DisplayName { get; set; } = string.Empty;

        [JsonProperty("desired_state")]
        public string DesiredState { get; set; } = string.Empty;

        [JsonProperty("observed_state")]
        public string ObservedState { get; set; } = string.Empty;

        [JsonProperty("worker_process_id")]
        public int? WorkerProcessId { get; set; }

        [JsonProperty("worker_instance_id")]
        public string? WorkerInstanceId { get; set; }

        [JsonProperty("loaded_snapshot_fingerprint")]
        public string? LoadedSnapshotFingerprint { get; set; }

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
    /// WorkflowAppRuntime 不可变 revision 响应模型。
    /// </summary>
    public sealed class WorkflowRuntimeRevisionResponse
    {
        [JsonProperty("format_id")]
        public string FormatId { get; set; } = string.Empty;

        [JsonProperty("workflow_runtime_revision_id")]
        public string WorkflowRuntimeRevisionId { get; set; } = string.Empty;

        [JsonProperty("workflow_runtime_id")]
        public string WorkflowRuntimeId { get; set; } = string.Empty;

        [JsonProperty("generation")]
        public int Generation { get; set; }

        [JsonProperty("workflow_app_version_id")]
        public string WorkflowAppVersionId { get; set; } = string.Empty;

        [JsonProperty("execution_policy_snapshot_object_key")]
        public string? ExecutionPolicySnapshotObjectKey { get; set; }

        [JsonProperty("expected_snapshot_fingerprint")]
        public string ExpectedSnapshotFingerprint { get; set; } = string.Empty;

        [JsonProperty("state")]
        public string State { get; set; } = string.Empty;

        [JsonProperty("created_at")]
        public string CreatedAt { get; set; } = string.Empty;

        [JsonProperty("activated_at")]
        public string? ActivatedAt { get; set; }

        [JsonProperty("failed_at")]
        public string? FailedAt { get; set; }

        [JsonProperty("error")]
        public string? Error { get; set; }

        [JsonProperty("created_by")]
        public string? CreatedBy { get; set; }
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
