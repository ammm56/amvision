using System.Collections.Generic;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace Amvision.TriggerSources;

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

/// <summary>
/// WorkflowAppRuntime 响应合同。
/// </summary>
public sealed class WorkflowAppRuntimeContract
{
    [JsonPropertyName("format_id")]
    public string FormatId { get; set; } = string.Empty;

    [JsonPropertyName("workflow_runtime_id")]
    public string WorkflowRuntimeId { get; set; } = string.Empty;

    [JsonPropertyName("project_id")]
    public string ProjectId { get; set; } = string.Empty;

    [JsonPropertyName("application_id")]
    public string ApplicationId { get; set; } = string.Empty;

    [JsonPropertyName("execution_policy_id")]
    public string? ExecutionPolicyId { get; set; }

    [JsonPropertyName("display_name")]
    public string DisplayName { get; set; } = string.Empty;

    [JsonPropertyName("desired_state")]
    public string DesiredState { get; set; } = string.Empty;

    [JsonPropertyName("observed_state")]
    public string ObservedState { get; set; } = string.Empty;

    [JsonPropertyName("worker_process_id")]
    public int? WorkerProcessId { get; set; }

    [JsonPropertyName("last_started_at")]
    public string? LastStartedAt { get; set; }

    [JsonPropertyName("last_stopped_at")]
    public string? LastStoppedAt { get; set; }

    [JsonPropertyName("heartbeat_at")]
    public string? HeartbeatAt { get; set; }

    [JsonPropertyName("last_error")]
    public JsonElement? LastError { get; set; }

    [JsonPropertyName("health_summary")]
    public IDictionary<string, JsonElement> HealthSummary { get; set; } = new Dictionary<string, JsonElement>();

    [JsonPropertyName("metadata")]
    public IDictionary<string, JsonElement> Metadata { get; set; } = new Dictionary<string, JsonElement>();

    [JsonPropertyName("created_at")]
    public string CreatedAt { get; set; } = string.Empty;

    [JsonPropertyName("updated_at")]
    public string UpdatedAt { get; set; } = string.Empty;
}

/// <summary>
/// WorkflowAppRuntime 事件响应合同。
/// </summary>
public sealed class WorkflowAppRuntimeEventContract
{
    [JsonPropertyName("format_id")]
    public string FormatId { get; set; } = string.Empty;

    [JsonPropertyName("workflow_runtime_id")]
    public string WorkflowRuntimeId { get; set; } = string.Empty;

    [JsonPropertyName("sequence")]
    public long Sequence { get; set; }

    [JsonPropertyName("event_type")]
    public string EventType { get; set; } = string.Empty;

    [JsonPropertyName("occurred_at")]
    public string OccurredAt { get; set; } = string.Empty;

    [JsonPropertyName("payload")]
    public IDictionary<string, JsonElement> Payload { get; set; } = new Dictionary<string, JsonElement>();
}

/// <summary>
/// WorkflowAppRuntime worker instance 响应合同。
/// </summary>
public sealed class WorkflowAppRuntimeInstanceContract
{
    [JsonPropertyName("format_id")]
    public string FormatId { get; set; } = string.Empty;

    [JsonPropertyName("workflow_runtime_id")]
    public string WorkflowRuntimeId { get; set; } = string.Empty;

    [JsonPropertyName("instance_id")]
    public string InstanceId { get; set; } = string.Empty;

    [JsonPropertyName("state")]
    public string State { get; set; } = string.Empty;

    [JsonPropertyName("process_id")]
    public int? ProcessId { get; set; }

    [JsonPropertyName("health_summary")]
    public IDictionary<string, JsonElement> HealthSummary { get; set; } = new Dictionary<string, JsonElement>();
}

/// <summary>
/// WorkflowRun 响应合同。
/// </summary>
public sealed class WorkflowRunContract
{
    [JsonPropertyName("format_id")]
    public string FormatId { get; set; } = string.Empty;

    [JsonPropertyName("workflow_run_id")]
    public string WorkflowRunId { get; set; } = string.Empty;

    [JsonPropertyName("workflow_runtime_id")]
    public string? WorkflowRuntimeId { get; set; }

    [JsonPropertyName("project_id")]
    public string ProjectId { get; set; } = string.Empty;

    [JsonPropertyName("application_id")]
    public string ApplicationId { get; set; } = string.Empty;

    [JsonPropertyName("state")]
    public string State { get; set; } = string.Empty;

    [JsonPropertyName("input_payload")]
    public IDictionary<string, JsonElement> InputPayload { get; set; } = new Dictionary<string, JsonElement>();

    [JsonPropertyName("outputs")]
    public IDictionary<string, JsonElement> Outputs { get; set; } = new Dictionary<string, JsonElement>();

    [JsonPropertyName("template_outputs")]
    public IDictionary<string, JsonElement> TemplateOutputs { get; set; } = new Dictionary<string, JsonElement>();

    [JsonPropertyName("node_records")]
    public IList<JsonElement> NodeRecords { get; set; } = new List<JsonElement>();

    [JsonPropertyName("error_message")]
    public string? ErrorMessage { get; set; }

    [JsonPropertyName("metadata")]
    public IDictionary<string, JsonElement> Metadata { get; set; } = new Dictionary<string, JsonElement>();

    [JsonPropertyName("created_at")]
    public string CreatedAt { get; set; } = string.Empty;

    [JsonPropertyName("updated_at")]
    public string UpdatedAt { get; set; } = string.Empty;
}

/// <summary>
/// WorkflowRun 事件响应合同。
/// </summary>
public sealed class WorkflowRunEventContract
{
    [JsonPropertyName("format_id")]
    public string FormatId { get; set; } = string.Empty;

    [JsonPropertyName("workflow_run_id")]
    public string WorkflowRunId { get; set; } = string.Empty;

    [JsonPropertyName("sequence")]
    public long Sequence { get; set; }

    [JsonPropertyName("event_type")]
    public string EventType { get; set; } = string.Empty;

    [JsonPropertyName("occurred_at")]
    public string OccurredAt { get; set; } = string.Empty;

    [JsonPropertyName("payload")]
    public IDictionary<string, JsonElement> Payload { get; set; } = new Dictionary<string, JsonElement>();
}

/// <summary>
/// TriggerSource input binding 映射项。
/// </summary>
public sealed class WorkflowTriggerInputBindingMappingItem
{
    [JsonPropertyName("source")]
    public string? Source { get; set; }

    [JsonPropertyName("value")]
    public object? Value { get; set; }

    [JsonPropertyName("required")]
    public bool Required { get; set; } = true;

    [JsonPropertyName("payload_type_id")]
    public string? PayloadTypeId { get; set; }

    [JsonPropertyName("metadata")]
    public IDictionary<string, object?> Metadata { get; } = new Dictionary<string, object?>();
}

/// <summary>
/// TriggerSource 结果映射。
/// </summary>
public sealed class WorkflowTriggerResultMapping
{
    [JsonPropertyName("result_binding")]
    public string ResultBinding { get; set; } = "workflow_result";

    [JsonPropertyName("result_mode")]
    public string ResultMode { get; set; } = "accepted-then-query";

    [JsonPropertyName("reply_timeout_seconds")]
    public int? ReplyTimeoutSeconds { get; set; }

    [JsonPropertyName("metadata")]
    public IDictionary<string, object?> Metadata { get; } = new Dictionary<string, object?>();
}

/// <summary>
/// WorkflowTriggerSource 创建请求。
/// </summary>
public sealed class WorkflowTriggerSourceCreateRequest
{
    [JsonPropertyName("trigger_source_id")]
    public string TriggerSourceId { get; set; } = string.Empty;

    [JsonPropertyName("project_id")]
    public string ProjectId { get; set; } = string.Empty;

    [JsonPropertyName("display_name")]
    public string DisplayName { get; set; } = string.Empty;

    [JsonPropertyName("trigger_kind")]
    public string TriggerKind { get; set; } = "zeromq-topic";

    [JsonPropertyName("workflow_runtime_id")]
    public string WorkflowRuntimeId { get; set; } = string.Empty;

    [JsonPropertyName("submit_mode")]
    public string SubmitMode { get; set; } = "async";

    [JsonPropertyName("enabled")]
    public bool Enabled { get; set; }

    [JsonPropertyName("transport_config")]
    public IDictionary<string, object?> TransportConfig { get; } = new Dictionary<string, object?>();

    [JsonPropertyName("match_rule")]
    public IDictionary<string, object?> MatchRule { get; } = new Dictionary<string, object?>();

    [JsonPropertyName("input_binding_mapping")]
    public IDictionary<string, WorkflowTriggerInputBindingMappingItem> InputBindingMapping { get; } =
        new Dictionary<string, WorkflowTriggerInputBindingMappingItem>();

    [JsonPropertyName("result_mapping")]
    public WorkflowTriggerResultMapping ResultMapping { get; set; } = new WorkflowTriggerResultMapping();

    [JsonPropertyName("default_execution_metadata")]
    public IDictionary<string, object?> DefaultExecutionMetadata { get; } = new Dictionary<string, object?>();

    [JsonPropertyName("ack_policy")]
    public string AckPolicy { get; set; } = "ack-after-run-created";

    [JsonPropertyName("result_mode")]
    public string ResultMode { get; set; } = "accepted-then-query";

    [JsonPropertyName("reply_timeout_seconds")]
    public int? ReplyTimeoutSeconds { get; set; }

    [JsonPropertyName("debounce_window_ms")]
    public int? DebounceWindowMs { get; set; }

    [JsonPropertyName("idempotency_key_path")]
    public string? IdempotencyKeyPath { get; set; }

    [JsonPropertyName("metadata")]
    public IDictionary<string, object?> Metadata { get; } = new Dictionary<string, object?>();
}

/// <summary>
/// WorkflowTriggerSource 响应合同。
/// </summary>
public sealed class WorkflowTriggerSourceContract
{
    [JsonPropertyName("format_id")]
    public string FormatId { get; set; } = string.Empty;

    [JsonPropertyName("trigger_source_id")]
    public string TriggerSourceId { get; set; } = string.Empty;

    [JsonPropertyName("project_id")]
    public string ProjectId { get; set; } = string.Empty;

    [JsonPropertyName("display_name")]
    public string DisplayName { get; set; } = string.Empty;

    [JsonPropertyName("trigger_kind")]
    public string TriggerKind { get; set; } = string.Empty;

    [JsonPropertyName("workflow_runtime_id")]
    public string WorkflowRuntimeId { get; set; } = string.Empty;

    [JsonPropertyName("submit_mode")]
    public string SubmitMode { get; set; } = string.Empty;

    [JsonPropertyName("enabled")]
    public bool Enabled { get; set; }

    [JsonPropertyName("desired_state")]
    public string DesiredState { get; set; } = string.Empty;

    [JsonPropertyName("observed_state")]
    public string ObservedState { get; set; } = string.Empty;

    [JsonPropertyName("transport_config")]
    public IDictionary<string, JsonElement> TransportConfig { get; set; } = new Dictionary<string, JsonElement>();

    [JsonPropertyName("input_binding_mapping")]
    public IDictionary<string, JsonElement> InputBindingMapping { get; set; } = new Dictionary<string, JsonElement>();

    [JsonPropertyName("result_mapping")]
    public JsonElement? ResultMapping { get; set; }

    [JsonPropertyName("health_summary")]
    public IDictionary<string, JsonElement> HealthSummary { get; set; } = new Dictionary<string, JsonElement>();

    [JsonPropertyName("last_triggered_at")]
    public string? LastTriggeredAt { get; set; }

    [JsonPropertyName("last_error")]
    public JsonElement? LastError { get; set; }

    [JsonPropertyName("metadata")]
    public IDictionary<string, JsonElement> Metadata { get; set; } = new Dictionary<string, JsonElement>();

    [JsonPropertyName("created_at")]
    public string CreatedAt { get; set; } = string.Empty;

    [JsonPropertyName("updated_at")]
    public string UpdatedAt { get; set; } = string.Empty;
}

/// <summary>
/// WorkflowTriggerSource health 摘要。
/// </summary>
public sealed class WorkflowTriggerSourceHealthSummary
{
    [JsonPropertyName("adapter_configured")]
    public bool AdapterConfigured { get; set; }

    [JsonPropertyName("adapter_running")]
    public bool AdapterRunning { get; set; }

    [JsonPropertyName("request_count")]
    public int RequestCount { get; set; }

    [JsonPropertyName("success_count")]
    public int SuccessCount { get; set; }

    [JsonPropertyName("error_count")]
    public int ErrorCount { get; set; }

    [JsonPropertyName("timeout_count")]
    public int TimeoutCount { get; set; }

    [JsonPropertyName("recent_error")]
    public JsonElement? RecentError { get; set; }

    [JsonPropertyName("supervisor")]
    public IDictionary<string, JsonElement> Supervisor { get; set; } = new Dictionary<string, JsonElement>();
}

/// <summary>
/// WorkflowTriggerSource health 响应合同。
/// </summary>
public sealed class WorkflowTriggerSourceHealthContract
{
    [JsonPropertyName("trigger_source_id")]
    public string TriggerSourceId { get; set; } = string.Empty;

    [JsonPropertyName("enabled")]
    public bool Enabled { get; set; }

    [JsonPropertyName("desired_state")]
    public string DesiredState { get; set; } = string.Empty;

    [JsonPropertyName("observed_state")]
    public string ObservedState { get; set; } = string.Empty;

    [JsonPropertyName("last_triggered_at")]
    public string? LastTriggeredAt { get; set; }

    [JsonPropertyName("last_error")]
    public JsonElement? LastError { get; set; }

    [JsonPropertyName("health_summary")]
    public WorkflowTriggerSourceHealthSummary HealthSummary { get; set; } = new WorkflowTriggerSourceHealthSummary();
}
