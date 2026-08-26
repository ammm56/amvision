using System.Collections.Generic;
using Newtonsoft.Json.Linq;
using Newtonsoft.Json;

namespace Amvar.Vision
{

    /// <summary>
    /// WorkflowTriggerSource health 摘要。
    /// </summary>
    public sealed class WorkflowTriggerSourceHealthSummary
    {
        [JsonProperty("adapter_configured")]
        public bool AdapterConfigured { get; set; }

        [JsonProperty("adapter_running")]
        public bool AdapterRunning { get; set; }

        [JsonProperty("request_count")]
        public int RequestCount { get; set; }

        [JsonProperty("request_count_rollover_count")]
        public int RequestCountRolloverCount { get; set; }

        [JsonProperty("success_count")]
        public int SuccessCount { get; set; }

        [JsonProperty("success_count_rollover_count")]
        public int SuccessCountRolloverCount { get; set; }

        [JsonProperty("error_count")]
        public int ErrorCount { get; set; }

        [JsonProperty("error_count_rollover_count")]
        public int ErrorCountRolloverCount { get; set; }

        [JsonProperty("timeout_count")]
        public int TimeoutCount { get; set; }

        [JsonProperty("timeout_count_rollover_count")]
        public int TimeoutCountRolloverCount { get; set; }

        [JsonProperty("busy_count")]
        public int BusyCount { get; set; }

        [JsonProperty("capacity_reject_count")]
        public int CapacityRejectCount { get; set; }

        [JsonProperty("request_timeout_count")]
        public int RequestTimeoutCount { get; set; }

        [JsonProperty("response_ack_timeout_count")]
        public int ResponseAckTimeoutCount { get; set; }

        [JsonProperty("cancel_count")]
        public int CancelCount { get; set; }

        [JsonProperty("recent_error")]
        public JToken? RecentError { get; set; }

        [JsonProperty("supervisor")]
        public IDictionary<string, JToken> Supervisor { get; set; } = new Dictionary<string, JToken>();
    }

    /// <summary>
    /// WorkflowTriggerSource health 响应模型。
    /// </summary>
    public sealed class WorkflowTriggerSourceHealthResponse
    {
        [JsonProperty("trigger_source_id")]
        public string TriggerSourceId { get; set; } = string.Empty;

        [JsonProperty("enabled")]
        public bool Enabled { get; set; }

        [JsonProperty("desired_state")]
        public string DesiredState { get; set; } = string.Empty;

        [JsonProperty("observed_state")]
        public string ObservedState { get; set; } = string.Empty;

        [JsonProperty("last_triggered_at")]
        public string? LastTriggeredAt { get; set; }

        [JsonProperty("last_error")]
        public JToken? LastError { get; set; }

        [JsonProperty("health_summary")]
        public WorkflowTriggerSourceHealthSummary HealthSummary { get; set; } = new WorkflowTriggerSourceHealthSummary();
    }
}
