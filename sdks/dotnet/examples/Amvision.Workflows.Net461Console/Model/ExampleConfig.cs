using System;
using System.Text.Json.Serialization;

namespace Amvision.Workflows.Examples.Net461Console.Model;

internal sealed class ExampleConfig
{
    [JsonPropertyName("backend")]
    public BackendConfig Backend { get; set; } = new BackendConfig();

    [JsonPropertyName("workflow_runtime")]
    public WorkflowRuntimeConfig WorkflowRuntime { get; set; } = new WorkflowRuntimeConfig();

    [JsonPropertyName("invoke")]
    public InvokeConfig Invoke { get; set; } = new InvokeConfig();

    [JsonPropertyName("cleanup")]
    public CleanupConfig Cleanup { get; set; } = new CleanupConfig();

    public void Validate()
    {
        Backend.Validate();
        WorkflowRuntime.Validate();
        Invoke.Validate();
    }
}

internal sealed class BackendConfig
{
    [JsonPropertyName("base_api_url")]
    public string BaseApiUrl { get; set; } = "http://127.0.0.1:8000";

    [JsonPropertyName("access_token")]
    public string AccessToken { get; set; } = "amvision-default-user-token";

    [JsonPropertyName("project_id")]
    public string ProjectId { get; set; } = "project-1";

    [JsonPropertyName("http_timeout_seconds")]
    public int HttpTimeoutSeconds { get; set; } = 60;

    public void Validate()
    {
        if (string.IsNullOrWhiteSpace(BaseApiUrl))
        {
            throw new InvalidOperationException("config.backend.base_api_url cannot be empty.");
        }

        if (string.IsNullOrWhiteSpace(AccessToken))
        {
            throw new InvalidOperationException("config.backend.access_token cannot be empty.");
        }

        if (string.IsNullOrWhiteSpace(ProjectId))
        {
            throw new InvalidOperationException("config.backend.project_id cannot be empty.");
        }

        if (HttpTimeoutSeconds <= 0)
        {
            throw new InvalidOperationException("config.backend.http_timeout_seconds must be greater than zero.");
        }
    }
}

internal sealed class WorkflowRuntimeConfig
{
    [JsonPropertyName("workflow_runtime_id")]
    public string? WorkflowRuntimeId { get; set; }

    [JsonPropertyName("application_id")]
    public string? ApplicationId { get; set; }

    [JsonPropertyName("execution_policy_id")]
    public string? ExecutionPolicyId { get; set; }

    [JsonPropertyName("display_name")]
    public string DisplayName { get; set; } = "dotnet-net461-example-runtime";

    [JsonPropertyName("request_timeout_seconds")]
    public int RequestTimeoutSeconds { get; set; } = 30;

    [JsonPropertyName("heartbeat_interval_seconds")]
    public int HeartbeatIntervalSeconds { get; set; } = 5;

    [JsonPropertyName("heartbeat_timeout_seconds")]
    public int HeartbeatTimeoutSeconds { get; set; } = 15;

    [JsonPropertyName("restart_runtime")]
    public bool RestartRuntime { get; set; }

    public void Validate()
    {
        if (string.IsNullOrWhiteSpace(WorkflowRuntimeId)
            && string.IsNullOrWhiteSpace(ApplicationId))
        {
            throw new InvalidOperationException(
                "Set config.workflow_runtime.workflow_runtime_id to reuse a runtime, or set config.workflow_runtime.application_id to create one.");
        }

        if (string.IsNullOrWhiteSpace(DisplayName))
        {
            throw new InvalidOperationException("config.workflow_runtime.display_name cannot be empty.");
        }

        if (RequestTimeoutSeconds <= 0)
        {
            throw new InvalidOperationException("config.workflow_runtime.request_timeout_seconds must be greater than zero.");
        }

        if (HeartbeatIntervalSeconds <= 0)
        {
            throw new InvalidOperationException("config.workflow_runtime.heartbeat_interval_seconds must be greater than zero.");
        }

        if (HeartbeatTimeoutSeconds <= 0)
        {
            throw new InvalidOperationException("config.workflow_runtime.heartbeat_timeout_seconds must be greater than zero.");
        }
    }
}

internal sealed class InvokeConfig
{
    [JsonPropertyName("image_path")]
    public string? ImagePath { get; set; }

    [JsonPropertyName("timeout_seconds")]
    public int TimeoutSeconds { get; set; } = 30;

    [JsonPropertyName("event_limit")]
    public int EventLimit { get; set; } = 20;

    [JsonPropertyName("event_preview_count")]
    public int EventPreviewCount { get; set; } = 5;

    [JsonPropertyName("source")]
    public string Source { get; set; } = "dotnet-net461-console-example";

    [JsonPropertyName("sync_scenario")]
    public string SyncScenario { get; set; } = "sync-invoke";

    [JsonPropertyName("async_scenario")]
    public string AsyncScenario { get; set; } = "async-run";

    public void Validate()
    {
        if (TimeoutSeconds <= 0)
        {
            throw new InvalidOperationException("config.invoke.timeout_seconds must be greater than zero.");
        }

        if (EventLimit <= 0)
        {
            throw new InvalidOperationException("config.invoke.event_limit must be greater than zero.");
        }

        if (EventPreviewCount <= 0)
        {
            throw new InvalidOperationException("config.invoke.event_preview_count must be greater than zero.");
        }

        if (string.IsNullOrWhiteSpace(Source))
        {
            throw new InvalidOperationException("config.invoke.source cannot be empty.");
        }
    }
}

internal sealed class CleanupConfig
{
    [JsonPropertyName("stop_at_end")]
    public bool StopAtEnd { get; set; }

    [JsonPropertyName("delete_created_runtime")]
    public bool DeleteCreatedRuntime { get; set; }
}
