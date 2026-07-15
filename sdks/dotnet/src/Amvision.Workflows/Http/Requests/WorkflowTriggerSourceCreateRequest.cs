using System.Collections.Generic;
using Newtonsoft.Json;

namespace Amvision.Workflows
{

    /// <summary>
    /// TriggerSource input binding 映射项。
    /// </summary>
    public sealed class WorkflowTriggerInputBindingMappingItem
    {
        [JsonProperty("source")]
        public string? Source { get; set; }

        [JsonProperty("value")]
        public object? Value { get; set; }

        [JsonProperty("required")]
        public bool Required { get; set; } = true;

        [JsonProperty("payload_type_id")]
        public string? PayloadTypeId { get; set; }

        [JsonProperty("metadata")]
        public IDictionary<string, object?> Metadata { get; } = new Dictionary<string, object?>();
    }

    /// <summary>
    /// TriggerSource 结果映射。
    /// </summary>
    public sealed class WorkflowTriggerResultMapping
    {
        [JsonProperty("result_binding")]
        public string ResultBinding { get; set; } = "workflow_result";

        [JsonProperty("result_mode")]
        public string ResultMode { get; set; } = "sync-reply";

        [JsonProperty("reply_timeout_seconds")]
        public int? ReplyTimeoutSeconds { get; set; }

        [JsonProperty("metadata")]
        public IDictionary<string, object?> Metadata { get; } = new Dictionary<string, object?>();
    }

    /// <summary>
    /// WorkflowTriggerSource 创建请求。
    /// </summary>
    public sealed class WorkflowTriggerSourceCreateRequest
    {
        [JsonProperty("trigger_source_id")]
        public string TriggerSourceId { get; set; } = string.Empty;

        [JsonProperty("project_id")]
        public string ProjectId { get; set; } = string.Empty;

        [JsonProperty("display_name")]
        public string DisplayName { get; set; } = string.Empty;

        [JsonProperty("trigger_kind")]
        public string TriggerKind { get; set; } = "zeromq-topic";

        [JsonProperty("workflow_runtime_id")]
        public string WorkflowRuntimeId { get; set; } = string.Empty;

        [JsonProperty("submit_mode")]
        public string SubmitMode { get; set; } = "sync";

        [JsonProperty("enabled")]
        public bool Enabled { get; set; }

        [JsonProperty("transport_config")]
        public IDictionary<string, object?> TransportConfig { get; } = new Dictionary<string, object?>();

        [JsonProperty("match_rule")]
        public IDictionary<string, object?> MatchRule { get; } = new Dictionary<string, object?>();

        [JsonProperty("input_binding_mapping")]
        public IDictionary<string, WorkflowTriggerInputBindingMappingItem> InputBindingMapping { get; } =
            new Dictionary<string, WorkflowTriggerInputBindingMappingItem>();

        [JsonProperty("result_mapping")]
        public WorkflowTriggerResultMapping ResultMapping { get; set; } = new WorkflowTriggerResultMapping();

        [JsonProperty("default_execution_metadata")]
        public IDictionary<string, object?> DefaultExecutionMetadata { get; } = new Dictionary<string, object?>();

        [JsonProperty("ack_policy")]
        public string AckPolicy { get; set; } = "ack-after-run-finished";

        [JsonProperty("result_mode")]
        public string ResultMode { get; set; } = "sync-reply";

        [JsonProperty("reply_timeout_seconds")]
        public int? ReplyTimeoutSeconds { get; set; }

        [JsonProperty("debounce_window_ms")]
        public int? DebounceWindowMs { get; set; }

        [JsonProperty("idempotency_key_path")]
        public string? IdempotencyKeyPath { get; set; }

        [JsonProperty("metadata")]
        public IDictionary<string, object?> Metadata { get; } = new Dictionary<string, object?>();
    }
}
