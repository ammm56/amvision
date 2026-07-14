using System.Collections.Generic;
using System.Text.Json.Serialization;

namespace Amvision.Workflows
{

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
        public string ResultMode { get; set; } = "sync-reply";

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
        public string SubmitMode { get; set; } = "sync";

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
        public string AckPolicy { get; set; } = "ack-after-run-finished";

        [JsonPropertyName("result_mode")]
        public string ResultMode { get; set; } = "sync-reply";

        [JsonPropertyName("reply_timeout_seconds")]
        public int? ReplyTimeoutSeconds { get; set; }

        [JsonPropertyName("debounce_window_ms")]
        public int? DebounceWindowMs { get; set; }

        [JsonPropertyName("idempotency_key_path")]
        public string? IdempotencyKeyPath { get; set; }

        [JsonPropertyName("metadata")]
        public IDictionary<string, object?> Metadata { get; } = new Dictionary<string, object?>();
    }
}
