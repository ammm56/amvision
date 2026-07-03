using System;
using System.IO;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using Amvision.Workflows;
using Amvision.Workflows.Examples.Net461Console.Model;
using Amvision.Workflows.Examples.Net461Console.Tools;

namespace Amvision.Workflows.Examples.Net461Console;

internal sealed class WorkflowRuntimeControlExample
{
    private readonly AmvisionWorkflowClient client;
    private readonly ExampleConfig config;
    private bool createdRuntime;

    public WorkflowRuntimeControlExample(AmvisionWorkflowClient client)
    {
        this.client = client ?? throw new ArgumentNullException(nameof(client));
        config = ExampleConfigStore.Current;
    }

    public async Task RunAsync(CancellationToken cancellationToken)
    {
        WorkflowAppRuntimeResponse? runtime = null;
        try
        {
            await ListProjectRuntimesAsync(cancellationToken).ConfigureAwait(false);

            runtime = await ResolveRuntimeAsync(cancellationToken).ConfigureAwait(false);
            var runtimeId = runtime.WorkflowRuntimeId;

            runtime = await StartRuntimeAsync(runtimeId, cancellationToken).ConfigureAwait(false);
            runtime = await GetRuntimeHealthAsync(runtimeId, cancellationToken).ConfigureAwait(false);
            await ListRuntimeInstancesAsync(runtimeId, cancellationToken).ConfigureAwait(false);

            await InvokeRuntimeAppResultAsync(runtimeId, cancellationToken).ConfigureAwait(false);

            var run = await CreateWorkflowRunAsync(runtimeId, cancellationToken).ConfigureAwait(false);
            await GetWorkflowRunAsync(run.WorkflowRunId, cancellationToken).ConfigureAwait(false);
            await GetWorkflowRunEventsAsync(run.WorkflowRunId, cancellationToken).ConfigureAwait(false);

            await GetRuntimeEventsAsync(runtimeId, cancellationToken).ConfigureAwait(false);

            if (config.WorkflowRuntime.RestartRuntime)
            {
                runtime = await RestartRuntimeAsync(runtimeId, cancellationToken).ConfigureAwait(false);
                runtime = await GetRuntimeHealthAsync(runtimeId, cancellationToken).ConfigureAwait(false);
            }
        }
        finally
        {
            if (runtime is not null)
            {
                await CleanupRuntimeAsync(runtime.WorkflowRuntimeId, cancellationToken).ConfigureAwait(false);
            }
        }
    }

    private async Task ListProjectRuntimesAsync(CancellationToken cancellationToken)
    {
        var runtimes = await client.ListWorkflowAppRuntimeResponsesAsync(
            config.Backend.ProjectId,
            limit: 20,
            cancellationToken: cancellationToken).ConfigureAwait(false);

        Console.WriteLine("WorkflowAppRuntime list:");
        foreach (var runtime in runtimes)
        {
            Console.WriteLine($"  {runtime.WorkflowRuntimeId} | {runtime.DisplayName} | {runtime.DesiredState}/{runtime.ObservedState}");
        }
    }

    private async Task<WorkflowAppRuntimeResponse> ResolveRuntimeAsync(CancellationToken cancellationToken)
    {
        var workflowRuntimeId = NormalizeOptional(config.WorkflowRuntime.WorkflowRuntimeId);
        if (workflowRuntimeId is not null)
        {
            return await GetRuntimeAsync(workflowRuntimeId, cancellationToken).ConfigureAwait(false);
        }

        createdRuntime = true;
        return await CreateRuntimeAsync(cancellationToken).ConfigureAwait(false);
    }

    private async Task<WorkflowAppRuntimeResponse> CreateRuntimeAsync(CancellationToken cancellationToken)
    {
        var request = new WorkflowAppRuntimeCreateRequest
        {
            ProjectId = config.Backend.ProjectId,
            ApplicationId = NormalizeOptional(config.WorkflowRuntime.ApplicationId)
                ?? throw new InvalidOperationException("config.workflow_runtime.application_id is required when creating runtime."),
            ExecutionPolicyId = NormalizeOptional(config.WorkflowRuntime.ExecutionPolicyId),
            DisplayName = config.WorkflowRuntime.DisplayName,
            RequestTimeoutSeconds = config.WorkflowRuntime.RequestTimeoutSeconds,
            HeartbeatIntervalSeconds = config.WorkflowRuntime.HeartbeatIntervalSeconds,
            HeartbeatTimeoutSeconds = config.WorkflowRuntime.HeartbeatTimeoutSeconds
        };
        request.Metadata["source"] = config.Invoke.Source;

        var runtime = await client.CreateWorkflowAppRuntimeResponseAsync(
            request,
            cancellationToken).ConfigureAwait(false);

        Console.WriteLine($"Created runtime: {runtime.WorkflowRuntimeId}");
        return runtime;
    }

    private async Task<WorkflowAppRuntimeResponse> GetRuntimeAsync(string workflowRuntimeId, CancellationToken cancellationToken)
    {
        var runtime = await client.GetWorkflowAppRuntimeResponseAsync(
            workflowRuntimeId,
            cancellationToken).ConfigureAwait(false);

        Console.WriteLine($"Loaded runtime: {runtime.WorkflowRuntimeId} | {runtime.DesiredState}/{runtime.ObservedState}");
        return runtime;
    }

    private async Task<WorkflowAppRuntimeResponse> StartRuntimeAsync(string workflowRuntimeId, CancellationToken cancellationToken)
    {
        var runtime = await client.StartWorkflowAppRuntimeResponseAsync(
            workflowRuntimeId,
            cancellationToken).ConfigureAwait(false);

        Console.WriteLine($"Started runtime: {runtime.WorkflowRuntimeId} | {runtime.DesiredState}/{runtime.ObservedState}");
        return runtime;
    }

    private async Task<WorkflowAppRuntimeResponse> StopRuntimeAsync(string workflowRuntimeId, CancellationToken cancellationToken)
    {
        var runtime = await client.StopWorkflowAppRuntimeResponseAsync(
            workflowRuntimeId,
            cancellationToken).ConfigureAwait(false);

        Console.WriteLine($"Stopped runtime: {runtime.WorkflowRuntimeId} | {runtime.DesiredState}/{runtime.ObservedState}");
        return runtime;
    }

    private async Task<WorkflowAppRuntimeResponse> RestartRuntimeAsync(string workflowRuntimeId, CancellationToken cancellationToken)
    {
        var runtime = await client.RestartWorkflowAppRuntimeResponseAsync(
            workflowRuntimeId,
            cancellationToken).ConfigureAwait(false);

        Console.WriteLine($"Restarted runtime: {runtime.WorkflowRuntimeId} | {runtime.DesiredState}/{runtime.ObservedState}");
        return runtime;
    }

    private async Task<WorkflowAppRuntimeResponse> GetRuntimeHealthAsync(string workflowRuntimeId, CancellationToken cancellationToken)
    {
        var runtime = await client.GetWorkflowAppRuntimeHealthResponseAsync(
            workflowRuntimeId,
            cancellationToken).ConfigureAwait(false);

        Console.WriteLine($"Runtime health: {runtime.WorkflowRuntimeId} | {runtime.ObservedState}");
        if (runtime.HealthSummary.Count > 0)
        {
            Console.WriteLine($"  health keys: {string.Join(", ", runtime.HealthSummary.Keys)}");
        }

        return runtime;
    }

    private async Task ListRuntimeInstancesAsync(string workflowRuntimeId, CancellationToken cancellationToken)
    {
        var instances = await client.ListWorkflowAppRuntimeInstanceResponsesAsync(
            workflowRuntimeId,
            cancellationToken).ConfigureAwait(false);

        Console.WriteLine($"Runtime instances: {instances.Count}");
        foreach (var instance in instances)
        {
            Console.WriteLine($"  {instance.InstanceId} | {instance.State} | pid={instance.ProcessId}");
        }
    }

    private async Task InvokeRuntimeAppResultAsync(string workflowRuntimeId, CancellationToken cancellationToken)
    {
        var appResult = HasImageInput()
            ? await client.InvokeWorkflowAppRuntimeWithImageBase64AppResultResponseAsync(
                workflowRuntimeId,
                BuildImageInvokeRequest(config.Invoke.SyncScenario),
                cancellationToken).ConfigureAwait(false)
            : await client.InvokeWorkflowAppRuntimeAppResultResponseAsync(
                workflowRuntimeId,
                BuildJsonInvokeRequest(config.Invoke.SyncScenario),
                cancellationToken).ConfigureAwait(false);

        Console.WriteLine("Sync invoke app-result:");
        Console.WriteLine(appResult.BodyJson.ToString());
    }

    private async Task<WorkflowRunResponse> CreateWorkflowRunAsync(string workflowRuntimeId, CancellationToken cancellationToken)
    {
        var run = await client.CreateWorkflowRunResponseAsync(
            workflowRuntimeId,
            BuildWorkflowRunRequest(config.Invoke.AsyncScenario),
            cancellationToken).ConfigureAwait(false);

        Console.WriteLine($"Created WorkflowRun: {run.WorkflowRunId} | {run.State}");
        return run;
    }

    private async Task<WorkflowRunResponse> GetWorkflowRunAsync(string workflowRunId, CancellationToken cancellationToken)
    {
        var run = await client.GetWorkflowRunResponseAsync(
            workflowRunId,
            WorkflowResponseModes.Run,
            cancellationToken).ConfigureAwait(false);

        Console.WriteLine($"Loaded WorkflowRun: {run.WorkflowRunId} | {run.State}");
        return run;
    }

    private async Task GetWorkflowRunEventsAsync(string workflowRunId, CancellationToken cancellationToken)
    {
        var events = await client.GetWorkflowRunEventResponsesAsync(
            workflowRunId,
            limit: config.Invoke.EventLimit,
            cancellationToken: cancellationToken).ConfigureAwait(false);

        Console.WriteLine($"WorkflowRun events: {events.Count}");
        foreach (var item in events.Take(config.Invoke.EventPreviewCount))
        {
            Console.WriteLine($"  #{item.Sequence} {item.EventType}");
        }
    }

    private async Task GetRuntimeEventsAsync(string workflowRuntimeId, CancellationToken cancellationToken)
    {
        var events = await client.GetWorkflowAppRuntimeEventResponsesAsync(
            workflowRuntimeId,
            limit: config.Invoke.EventLimit,
            cancellationToken: cancellationToken).ConfigureAwait(false);

        Console.WriteLine($"Runtime events: {events.Count}");
        foreach (var item in events.Take(config.Invoke.EventPreviewCount))
        {
            Console.WriteLine($"  #{item.Sequence} {item.EventType}");
        }
    }

    private async Task DeleteRuntimeAsync(string workflowRuntimeId, CancellationToken cancellationToken)
    {
        var response = await client.DeleteWorkflowAppRuntimeAsync(
            workflowRuntimeId,
            cancellationToken).ConfigureAwait(false);
        response.EnsureSuccessStatusCode();
        Console.WriteLine($"Deleted runtime: {workflowRuntimeId}");
    }

    private async Task CleanupRuntimeAsync(string workflowRuntimeId, CancellationToken cancellationToken)
    {
        try
        {
            if (createdRuntime || config.Cleanup.StopAtEnd)
            {
                await StopRuntimeAsync(workflowRuntimeId, cancellationToken).ConfigureAwait(false);
            }

            if (createdRuntime && config.Cleanup.DeleteCreatedRuntime)
            {
                await DeleteRuntimeAsync(workflowRuntimeId, cancellationToken).ConfigureAwait(false);
            }
        }
        catch (Exception exception)
        {
            Console.Error.WriteLine($"Runtime cleanup failed: {exception.Message}");
        }
    }

    private WorkflowRuntimeInvokeRequest BuildWorkflowRunRequest(string scenario)
    {
        return HasImageInput()
            ? BuildImageInvokeRequest(scenario).ToWorkflowRuntimeInvokeRequest()
            : BuildJsonInvokeRequest(scenario);
    }

    private WorkflowRuntimeInvokeRequest BuildJsonInvokeRequest(string scenario)
    {
        var request = new WorkflowRuntimeInvokeRequest
        {
            TimeoutSeconds = config.Invoke.TimeoutSeconds
        };
        request.ExecutionMetadata["source"] = config.Invoke.Source;
        request.ExecutionMetadata["scenario"] = scenario;
        request.ExecutionMetadata["request_id"] = $"request-{Guid.NewGuid():N}";
        return request;
    }

    private WorkflowRuntimeImageInvokeRequest BuildImageInvokeRequest(string scenario)
    {
        var imagePath = NormalizeOptional(config.Invoke.ImagePath)
            ?? throw new InvalidOperationException("config.invoke.image_path is required.");
        if (!File.Exists(imagePath))
        {
            throw new FileNotFoundException("Input image file does not exist.", imagePath);
        }

        var request = new WorkflowRuntimeImageInvokeRequest
        {
            ImageBytes = File.ReadAllBytes(imagePath),
            MediaType = InferImageMediaType(imagePath),
            TimeoutSeconds = config.Invoke.TimeoutSeconds
        };
        request.ExecutionMetadata["source"] = config.Invoke.Source;
        request.ExecutionMetadata["scenario"] = scenario;
        request.ExecutionMetadata["request_id"] = $"request-{Guid.NewGuid():N}";
        return request;
    }

    private bool HasImageInput()
    {
        return NormalizeOptional(config.Invoke.ImagePath) is not null;
    }

    private static string InferImageMediaType(string imagePath)
    {
        var extension = Path.GetExtension(imagePath).ToLowerInvariant();
        switch (extension)
        {
            case ".jpg":
            case ".jpeg":
                return "image/jpeg";
            case ".png":
                return "image/png";
            case ".bmp":
                return "image/bmp";
            case ".webp":
                return "image/webp";
            case ".tif":
            case ".tiff":
                return "image/tiff";
            default:
                return "image/octet-stream";
        }
    }

    private static string? NormalizeOptional(string? value)
    {
        if (value is null)
        {
            return null;
        }

        var normalized = value.Trim();
        return normalized.Length == 0 ? null : normalized;
    }
}
