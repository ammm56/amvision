using System.Collections.Generic;
using System.Net.Http;
using System.Threading;
using System.Threading.Tasks;

namespace Amvision.Workflows;

public sealed partial class AmvisionWorkflowClient
{
    /// <summary>
    /// 按 Project id 列出 TriggerSource。
    /// </summary>
    public Task<AmvisionWorkflowApiResponse> ListTriggerSourcesAsync(
        string projectId,
        int offset = 0,
        int limit = 100,
        CancellationToken cancellationToken = default)
    {
        var path = WithQuery(
            $"{WorkflowApiPrefix}/trigger-sources",
            ("project_id", RequireId(projectId, nameof(projectId))),
            ("offset", offset),
            ("limit", limit));
        return SendAsync(HttpMethod.Get, path, content: null, cancellationToken);
    }

    /// <summary>
    /// 按 Project id 列出 TriggerSource，并返回 typed responses。
    /// </summary>
    public async Task<IReadOnlyList<WorkflowTriggerSourceResponse>> ListTriggerSourceResponsesAsync(
        string projectId,
        int offset = 0,
        int limit = 100,
        CancellationToken cancellationToken = default)
    {
        return ReadJsonList<WorkflowTriggerSourceResponse>(
            await ListTriggerSourcesAsync(projectId, offset, limit, cancellationToken).ConfigureAwait(false));
    }

    /// <summary>
    /// 读取一条 TriggerSource。
    /// </summary>
    public Task<AmvisionWorkflowApiResponse> GetTriggerSourceAsync(
        string triggerSourceId,
        CancellationToken cancellationToken = default)
    {
        return SendAsync(
            HttpMethod.Get,
            $"{WorkflowApiPrefix}/trigger-sources/{EncodePathSegment(RequireId(triggerSourceId, nameof(triggerSourceId)))}",
            content: null,
            cancellationToken);
    }

    /// <summary>
    /// 读取一条 TriggerSource，并返回 typed response。
    /// </summary>
    public async Task<WorkflowTriggerSourceResponse> GetTriggerSourceResponseAsync(
        string triggerSourceId,
        CancellationToken cancellationToken = default)
    {
        return ReadJson<WorkflowTriggerSourceResponse>(
            await GetTriggerSourceAsync(triggerSourceId, cancellationToken).ConfigureAwait(false));
    }

    /// <summary>
    /// 创建一条 TriggerSource。
    /// </summary>
    public Task<AmvisionWorkflowApiResponse> CreateTriggerSourceAsync(
        WorkflowTriggerSourceCreateRequest request,
        CancellationToken cancellationToken = default)
    {
        return SendAsync(HttpMethod.Post, $"{WorkflowApiPrefix}/trigger-sources", SerializeJson(request), cancellationToken);
    }

    /// <summary>
    /// 创建一条 TriggerSource，并返回 typed response。
    /// </summary>
    public async Task<WorkflowTriggerSourceResponse> CreateTriggerSourceResponseAsync(
        WorkflowTriggerSourceCreateRequest request,
        CancellationToken cancellationToken = default)
    {
        return ReadJson<WorkflowTriggerSourceResponse>(
            await CreateTriggerSourceAsync(request, cancellationToken).ConfigureAwait(false));
    }

    /// <summary>
    /// 启用一条 TriggerSource。
    /// </summary>
    public Task<AmvisionWorkflowApiResponse> EnableTriggerSourceAsync(
        string triggerSourceId,
        CancellationToken cancellationToken = default)
    {
        return SendAsync(
            HttpMethod.Post,
            $"{WorkflowApiPrefix}/trigger-sources/{EncodePathSegment(RequireId(triggerSourceId, nameof(triggerSourceId)))}/enable",
            content: null,
            cancellationToken);
    }

    /// <summary>
    /// 启用一条 TriggerSource，并返回 typed response。
    /// </summary>
    public async Task<WorkflowTriggerSourceResponse> EnableTriggerSourceResponseAsync(
        string triggerSourceId,
        CancellationToken cancellationToken = default)
    {
        return ReadJson<WorkflowTriggerSourceResponse>(
            await EnableTriggerSourceAsync(triggerSourceId, cancellationToken).ConfigureAwait(false));
    }

    /// <summary>
    /// 停用一条 TriggerSource。
    /// </summary>
    public Task<AmvisionWorkflowApiResponse> DisableTriggerSourceAsync(
        string triggerSourceId,
        CancellationToken cancellationToken = default)
    {
        return SendAsync(
            HttpMethod.Post,
            $"{WorkflowApiPrefix}/trigger-sources/{EncodePathSegment(RequireId(triggerSourceId, nameof(triggerSourceId)))}/disable",
            content: null,
            cancellationToken);
    }

    /// <summary>
    /// 停用一条 TriggerSource，并返回 typed response。
    /// </summary>
    public async Task<WorkflowTriggerSourceResponse> DisableTriggerSourceResponseAsync(
        string triggerSourceId,
        CancellationToken cancellationToken = default)
    {
        return ReadJson<WorkflowTriggerSourceResponse>(
            await DisableTriggerSourceAsync(triggerSourceId, cancellationToken).ConfigureAwait(false));
    }

    /// <summary>
    /// 删除一条 TriggerSource。
    /// </summary>
    public Task<AmvisionWorkflowApiResponse> DeleteTriggerSourceAsync(
        string triggerSourceId,
        CancellationToken cancellationToken = default)
    {
        return SendAsync(
            HttpMethod.Delete,
            $"{WorkflowApiPrefix}/trigger-sources/{EncodePathSegment(RequireId(triggerSourceId, nameof(triggerSourceId)))}",
            content: null,
            cancellationToken);
    }

    /// <summary>
    /// 查询一条 TriggerSource 的当前 health。
    /// </summary>
    public Task<AmvisionWorkflowApiResponse> GetTriggerSourceHealthAsync(
        string triggerSourceId,
        CancellationToken cancellationToken = default)
    {
        return SendAsync(
            HttpMethod.Get,
            $"{WorkflowApiPrefix}/trigger-sources/{EncodePathSegment(RequireId(triggerSourceId, nameof(triggerSourceId)))}/health",
            content: null,
            cancellationToken);
    }

    /// <summary>
    /// 查询一条 TriggerSource 的当前 health，并返回 typed response。
    /// </summary>
    public async Task<WorkflowTriggerSourceHealthResponse> GetTriggerSourceHealthResponseAsync(
        string triggerSourceId,
        CancellationToken cancellationToken = default)
    {
        return ReadJson<WorkflowTriggerSourceHealthResponse>(
            await GetTriggerSourceHealthAsync(triggerSourceId, cancellationToken).ConfigureAwait(false));
    }
}
