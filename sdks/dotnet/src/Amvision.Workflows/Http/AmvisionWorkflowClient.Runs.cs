using System.Collections.Generic;
using System.Net.Http;
using System.Threading;
using System.Threading.Tasks;

namespace Amvision.Workflows;

public sealed partial class AmvisionWorkflowClient
{
    /// <summary>
    /// 创建一条异步 WorkflowRun。
    /// </summary>
    public Task<AmvisionWorkflowApiResponse> CreateWorkflowRunAsync(
        string workflowRuntimeId,
        WorkflowRuntimeInvokeRequest request,
        CancellationToken cancellationToken = default)
    {
        if (request is null)
        {
            throw new ArgumentNullException(nameof(request));
        }
        return SendAsync(
            HttpMethod.Post,
            $"{WorkflowApiPrefix}/app-runtimes/{EncodePathSegment(RequireId(workflowRuntimeId, nameof(workflowRuntimeId)))}/runs",
            request.ToJson(),
            cancellationToken);
    }

    /// <summary>
    /// 创建一条异步 WorkflowRun，并返回 typed response。
    /// </summary>
    public async Task<WorkflowRunResponse> CreateWorkflowRunResponseAsync(
        string workflowRuntimeId,
        WorkflowRuntimeInvokeRequest request,
        CancellationToken cancellationToken = default)
    {
        return ReadJson<WorkflowRunResponse>(
            await CreateWorkflowRunAsync(workflowRuntimeId, request, cancellationToken).ConfigureAwait(false));
    }

    /// <summary>
    /// 通过通用 JSON 请求调用 WorkflowAppRuntime，默认返回 WorkflowRun 运行回执。
    /// </summary>
    public Task<AmvisionWorkflowApiResponse> InvokeWorkflowAppRuntimeAsync(
        string workflowRuntimeId,
        WorkflowRuntimeInvokeRequest request,
        CancellationToken cancellationToken = default)
    {
        return InvokeWorkflowAppRuntimeAsync(workflowRuntimeId, request, WorkflowResponseModes.Run, cancellationToken);
    }

    /// <summary>
    /// 通过通用 JSON 请求调用 WorkflowAppRuntime。
    /// </summary>
    public Task<AmvisionWorkflowApiResponse> InvokeWorkflowAppRuntimeAsync(
        string workflowRuntimeId,
        WorkflowRuntimeInvokeRequest request,
        string responseMode,
        CancellationToken cancellationToken = default)
    {
        if (request is null)
        {
            throw new ArgumentNullException(nameof(request));
        }
        var path = WithQuery(
            $"{WorkflowApiPrefix}/app-runtimes/{EncodePathSegment(RequireId(workflowRuntimeId, nameof(workflowRuntimeId)))}/invoke",
            ("response_mode", WorkflowResponseModes.Normalize(responseMode)));
        return SendAsync(HttpMethod.Post, path, request.ToJson(), cancellationToken);
    }

    /// <summary>
    /// 通过通用 JSON 请求调用 WorkflowAppRuntime，并返回 WorkflowRun typed response。
    /// </summary>
    public async Task<WorkflowRunResponse> InvokeWorkflowAppRuntimeResponseAsync(
        string workflowRuntimeId,
        WorkflowRuntimeInvokeRequest request,
        string responseMode = WorkflowResponseModes.Run,
        CancellationToken cancellationToken = default)
    {
        return ReadJson<WorkflowRunResponse>(
            await InvokeWorkflowAppRuntimeAsync(workflowRuntimeId, request, responseMode, cancellationToken).ConfigureAwait(false));
    }

    /// <summary>
    /// 通过 image-base64.v1 方式调用 WorkflowAppRuntime，默认返回 WorkflowRun 运行回执。
    /// </summary>
    public Task<AmvisionWorkflowApiResponse> InvokeWorkflowAppRuntimeWithImageBase64Async(
        string workflowRuntimeId,
        WorkflowRuntimeImageInvokeRequest request,
        CancellationToken cancellationToken = default)
    {
        return InvokeWorkflowAppRuntimeWithImageBase64Async(workflowRuntimeId, request, WorkflowResponseModes.Run, cancellationToken);
    }

    /// <summary>
    /// 通过 image-base64.v1 方式调用 WorkflowAppRuntime。
    /// </summary>
    public Task<AmvisionWorkflowApiResponse> InvokeWorkflowAppRuntimeWithImageBase64Async(
        string workflowRuntimeId,
        WorkflowRuntimeImageInvokeRequest request,
        string responseMode,
        CancellationToken cancellationToken = default)
    {
        if (request is null)
        {
            throw new ArgumentNullException(nameof(request));
        }
        return InvokeWorkflowAppRuntimeAsync(
            workflowRuntimeId,
            request.ToWorkflowRuntimeInvokeRequest(),
            responseMode,
            cancellationToken);
    }

    /// <summary>
    /// 通过 image-base64.v1 方式调用 WorkflowAppRuntime，并返回 WorkflowRun typed response。
    /// </summary>
    public async Task<WorkflowRunResponse> InvokeWorkflowAppRuntimeWithImageBase64ResponseAsync(
        string workflowRuntimeId,
        WorkflowRuntimeImageInvokeRequest request,
        string responseMode = WorkflowResponseModes.Run,
        CancellationToken cancellationToken = default)
    {
        return ReadJson<WorkflowRunResponse>(
            await InvokeWorkflowAppRuntimeWithImageBase64Async(workflowRuntimeId, request, responseMode, cancellationToken).ConfigureAwait(false));
    }

    /// <summary>
    /// 读取一条 WorkflowRun，默认返回 WorkflowRun 运行回执。
    /// </summary>
    public Task<AmvisionWorkflowApiResponse> GetWorkflowRunAsync(
        string workflowRunId,
        CancellationToken cancellationToken = default)
    {
        return GetWorkflowRunAsync(workflowRunId, WorkflowResponseModes.Run, cancellationToken);
    }

    /// <summary>
    /// 读取一条 WorkflowRun。
    /// </summary>
    public Task<AmvisionWorkflowApiResponse> GetWorkflowRunAsync(
        string workflowRunId,
        string responseMode,
        CancellationToken cancellationToken = default)
    {
        var path = WithQuery(
            $"{WorkflowApiPrefix}/runs/{EncodePathSegment(RequireId(workflowRunId, nameof(workflowRunId)))}",
            ("response_mode", WorkflowResponseModes.Normalize(responseMode)));
        return SendAsync(HttpMethod.Get, path, content: null, cancellationToken);
    }

    /// <summary>
    /// 读取一条 WorkflowRun，并返回 typed response。
    /// </summary>
    public async Task<WorkflowRunResponse> GetWorkflowRunResponseAsync(
        string workflowRunId,
        string responseMode = WorkflowResponseModes.Run,
        CancellationToken cancellationToken = default)
    {
        return ReadJson<WorkflowRunResponse>(
            await GetWorkflowRunAsync(workflowRunId, responseMode, cancellationToken).ConfigureAwait(false));
    }

    /// <summary>
    /// 读取 WorkflowRun 事件。
    /// </summary>
    public Task<AmvisionWorkflowApiResponse> GetWorkflowRunEventsAsync(
        string workflowRunId,
        long? afterSequence = null,
        int? limit = null,
        CancellationToken cancellationToken = default)
    {
        var path = WithQuery(
            $"{WorkflowApiPrefix}/runs/{EncodePathSegment(RequireId(workflowRunId, nameof(workflowRunId)))}/events",
            ("after_sequence", afterSequence),
            ("limit", limit));
        return SendAsync(HttpMethod.Get, path, content: null, cancellationToken);
    }

    /// <summary>
    /// 读取 WorkflowRun 事件，并返回 typed responses。
    /// </summary>
    public async Task<IReadOnlyList<WorkflowRunEventResponse>> GetWorkflowRunEventResponsesAsync(
        string workflowRunId,
        long? afterSequence = null,
        int? limit = null,
        CancellationToken cancellationToken = default)
    {
        return ReadJsonList<WorkflowRunEventResponse>(
            await GetWorkflowRunEventsAsync(workflowRunId, afterSequence, limit, cancellationToken).ConfigureAwait(false));
    }

    /// <summary>
    /// 取消一条异步 WorkflowRun。
    /// </summary>
    public Task<AmvisionWorkflowApiResponse> CancelWorkflowRunAsync(
        string workflowRunId,
        CancellationToken cancellationToken = default)
    {
        return SendAsync(
            HttpMethod.Post,
            $"{WorkflowApiPrefix}/runs/{EncodePathSegment(RequireId(workflowRunId, nameof(workflowRunId)))}/cancel",
            content: null,
            cancellationToken);
    }

    /// <summary>
    /// 取消一条异步 WorkflowRun，并返回 typed response。
    /// </summary>
    public async Task<WorkflowRunResponse> CancelWorkflowRunResponseAsync(
        string workflowRunId,
        CancellationToken cancellationToken = default)
    {
        return ReadJson<WorkflowRunResponse>(
            await CancelWorkflowRunAsync(workflowRunId, cancellationToken).ConfigureAwait(false));
    }
}
