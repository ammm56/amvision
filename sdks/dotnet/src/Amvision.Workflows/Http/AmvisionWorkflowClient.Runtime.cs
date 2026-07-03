using System.Collections.Generic;
using System.Net.Http;
using System.Threading;
using System.Threading.Tasks;

namespace Amvision.Workflows;

public sealed partial class AmvisionWorkflowClient
{
    /// <summary>
    /// 创建 WorkflowAppRuntime。
    /// </summary>
    public Task<AmvisionWorkflowApiResponse> CreateWorkflowAppRuntimeAsync(
        WorkflowAppRuntimeCreateRequest request,
        CancellationToken cancellationToken = default)
    {
        return SendAsync(HttpMethod.Post, $"{WorkflowApiPrefix}/app-runtimes", SerializeJson(request), cancellationToken);
    }

    /// <summary>
    /// 创建 WorkflowAppRuntime，并返回 typed response。
    /// </summary>
    public async Task<WorkflowAppRuntimeResponse> CreateWorkflowAppRuntimeResponseAsync(
        WorkflowAppRuntimeCreateRequest request,
        CancellationToken cancellationToken = default)
    {
        return ReadJson<WorkflowAppRuntimeResponse>(await CreateWorkflowAppRuntimeAsync(request, cancellationToken).ConfigureAwait(false));
    }

    /// <summary>
    /// 按 Project id 列出 WorkflowAppRuntime。
    /// </summary>
    public Task<AmvisionWorkflowApiResponse> ListWorkflowAppRuntimesAsync(
        string projectId,
        int offset = 0,
        int limit = 100,
        CancellationToken cancellationToken = default)
    {
        var path = WithQuery(
            $"{WorkflowApiPrefix}/app-runtimes",
            ("project_id", RequireId(projectId, nameof(projectId))),
            ("offset", offset),
            ("limit", limit));
        return SendAsync(HttpMethod.Get, path, content: null, cancellationToken);
    }

    /// <summary>
    /// 按 Project id 列出 WorkflowAppRuntime，并返回 typed responses。
    /// </summary>
    public async Task<IReadOnlyList<WorkflowAppRuntimeResponse>> ListWorkflowAppRuntimeResponsesAsync(
        string projectId,
        int offset = 0,
        int limit = 100,
        CancellationToken cancellationToken = default)
    {
        return ReadJsonList<WorkflowAppRuntimeResponse>(
            await ListWorkflowAppRuntimesAsync(projectId, offset, limit, cancellationToken).ConfigureAwait(false));
    }

    /// <summary>
    /// 读取一条 WorkflowAppRuntime。
    /// </summary>
    public Task<AmvisionWorkflowApiResponse> GetWorkflowAppRuntimeAsync(
        string workflowRuntimeId,
        CancellationToken cancellationToken = default)
    {
        return SendAsync(
            HttpMethod.Get,
            $"{WorkflowApiPrefix}/app-runtimes/{EncodePathSegment(RequireId(workflowRuntimeId, nameof(workflowRuntimeId)))}",
            content: null,
            cancellationToken);
    }

    /// <summary>
    /// 读取一条 WorkflowAppRuntime，并返回 typed response。
    /// </summary>
    public async Task<WorkflowAppRuntimeResponse> GetWorkflowAppRuntimeResponseAsync(
        string workflowRuntimeId,
        CancellationToken cancellationToken = default)
    {
        return ReadJson<WorkflowAppRuntimeResponse>(
            await GetWorkflowAppRuntimeAsync(workflowRuntimeId, cancellationToken).ConfigureAwait(false));
    }

    /// <summary>
    /// 读取 WorkflowAppRuntime 事件。
    /// </summary>
    public Task<AmvisionWorkflowApiResponse> GetWorkflowAppRuntimeEventsAsync(
        string workflowRuntimeId,
        long? afterSequence = null,
        int? limit = null,
        CancellationToken cancellationToken = default)
    {
        var path = WithQuery(
            $"{WorkflowApiPrefix}/app-runtimes/{EncodePathSegment(RequireId(workflowRuntimeId, nameof(workflowRuntimeId)))}/events",
            ("after_sequence", afterSequence),
            ("limit", limit));
        return SendAsync(HttpMethod.Get, path, content: null, cancellationToken);
    }

    /// <summary>
    /// 读取 WorkflowAppRuntime 事件，并返回 typed responses。
    /// </summary>
    public async Task<IReadOnlyList<WorkflowAppRuntimeEventResponse>> GetWorkflowAppRuntimeEventResponsesAsync(
        string workflowRuntimeId,
        long? afterSequence = null,
        int? limit = null,
        CancellationToken cancellationToken = default)
    {
        return ReadJsonList<WorkflowAppRuntimeEventResponse>(
            await GetWorkflowAppRuntimeEventsAsync(workflowRuntimeId, afterSequence, limit, cancellationToken).ConfigureAwait(false));
    }

    /// <summary>
    /// 启动一个 WorkflowAppRuntime。
    /// </summary>
    public Task<AmvisionWorkflowApiResponse> StartWorkflowAppRuntimeAsync(
        string workflowRuntimeId,
        CancellationToken cancellationToken = default)
    {
        return SendAsync(
            HttpMethod.Post,
            $"{WorkflowApiPrefix}/app-runtimes/{EncodePathSegment(RequireId(workflowRuntimeId, nameof(workflowRuntimeId)))}/start",
            content: null,
            cancellationToken);
    }

    /// <summary>
    /// 启动一个 WorkflowAppRuntime，并返回 typed response。
    /// </summary>
    public async Task<WorkflowAppRuntimeResponse> StartWorkflowAppRuntimeResponseAsync(
        string workflowRuntimeId,
        CancellationToken cancellationToken = default)
    {
        return ReadJson<WorkflowAppRuntimeResponse>(
            await StartWorkflowAppRuntimeAsync(workflowRuntimeId, cancellationToken).ConfigureAwait(false));
    }

    /// <summary>
    /// 停止一个 WorkflowAppRuntime。
    /// </summary>
    public Task<AmvisionWorkflowApiResponse> StopWorkflowAppRuntimeAsync(
        string workflowRuntimeId,
        CancellationToken cancellationToken = default)
    {
        return SendAsync(
            HttpMethod.Post,
            $"{WorkflowApiPrefix}/app-runtimes/{EncodePathSegment(RequireId(workflowRuntimeId, nameof(workflowRuntimeId)))}/stop",
            content: null,
            cancellationToken);
    }

    /// <summary>
    /// 停止一个 WorkflowAppRuntime，并返回 typed response。
    /// </summary>
    public async Task<WorkflowAppRuntimeResponse> StopWorkflowAppRuntimeResponseAsync(
        string workflowRuntimeId,
        CancellationToken cancellationToken = default)
    {
        return ReadJson<WorkflowAppRuntimeResponse>(
            await StopWorkflowAppRuntimeAsync(workflowRuntimeId, cancellationToken).ConfigureAwait(false));
    }

    /// <summary>
    /// 重启一个 WorkflowAppRuntime。
    /// </summary>
    public Task<AmvisionWorkflowApiResponse> RestartWorkflowAppRuntimeAsync(
        string workflowRuntimeId,
        CancellationToken cancellationToken = default)
    {
        return SendAsync(
            HttpMethod.Post,
            $"{WorkflowApiPrefix}/app-runtimes/{EncodePathSegment(RequireId(workflowRuntimeId, nameof(workflowRuntimeId)))}/restart",
            content: null,
            cancellationToken);
    }

    /// <summary>
    /// 重启一个 WorkflowAppRuntime，并返回 typed response。
    /// </summary>
    public async Task<WorkflowAppRuntimeResponse> RestartWorkflowAppRuntimeResponseAsync(
        string workflowRuntimeId,
        CancellationToken cancellationToken = default)
    {
        return ReadJson<WorkflowAppRuntimeResponse>(
            await RestartWorkflowAppRuntimeAsync(workflowRuntimeId, cancellationToken).ConfigureAwait(false));
    }

    /// <summary>
    /// 查询一个 WorkflowAppRuntime 的当前 health。
    /// </summary>
    public Task<AmvisionWorkflowApiResponse> GetWorkflowAppRuntimeHealthAsync(
        string workflowRuntimeId,
        CancellationToken cancellationToken = default)
    {
        return SendAsync(
            HttpMethod.Get,
            $"{WorkflowApiPrefix}/app-runtimes/{EncodePathSegment(RequireId(workflowRuntimeId, nameof(workflowRuntimeId)))}/health",
            content: null,
            cancellationToken);
    }

    /// <summary>
    /// 查询一个 WorkflowAppRuntime 的当前 health，并返回 typed response。
    /// </summary>
    public async Task<WorkflowAppRuntimeResponse> GetWorkflowAppRuntimeHealthResponseAsync(
        string workflowRuntimeId,
        CancellationToken cancellationToken = default)
    {
        return ReadJson<WorkflowAppRuntimeResponse>(
            await GetWorkflowAppRuntimeHealthAsync(workflowRuntimeId, cancellationToken).ConfigureAwait(false));
    }

    /// <summary>
    /// 列出一个 WorkflowAppRuntime 的 worker instances。
    /// </summary>
    public Task<AmvisionWorkflowApiResponse> ListWorkflowAppRuntimeInstancesAsync(
        string workflowRuntimeId,
        CancellationToken cancellationToken = default)
    {
        return SendAsync(
            HttpMethod.Get,
            $"{WorkflowApiPrefix}/app-runtimes/{EncodePathSegment(RequireId(workflowRuntimeId, nameof(workflowRuntimeId)))}/instances",
            content: null,
            cancellationToken);
    }

    /// <summary>
    /// 列出一个 WorkflowAppRuntime 的 worker instances，并返回 typed responses。
    /// </summary>
    public async Task<IReadOnlyList<WorkflowAppRuntimeInstanceResponse>> ListWorkflowAppRuntimeInstanceResponsesAsync(
        string workflowRuntimeId,
        CancellationToken cancellationToken = default)
    {
        return ReadJsonList<WorkflowAppRuntimeInstanceResponse>(
            await ListWorkflowAppRuntimeInstancesAsync(workflowRuntimeId, cancellationToken).ConfigureAwait(false));
    }

    /// <summary>
    /// 删除一条 WorkflowAppRuntime。
    /// </summary>
    public Task<AmvisionWorkflowApiResponse> DeleteWorkflowAppRuntimeAsync(
        string workflowRuntimeId,
        CancellationToken cancellationToken = default)
    {
        return SendAsync(
            HttpMethod.Delete,
            $"{WorkflowApiPrefix}/app-runtimes/{EncodePathSegment(RequireId(workflowRuntimeId, nameof(workflowRuntimeId)))}",
            content: null,
            cancellationToken);
    }
}
