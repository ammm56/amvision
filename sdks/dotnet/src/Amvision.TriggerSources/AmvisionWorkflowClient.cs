using System;
using System.Collections.Generic;
using System.Globalization;
using System.Net.Http;
using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;
using System.Threading;
using System.Threading.Tasks;

namespace Amvision.TriggerSources;

/// <summary>
/// backend-service Workflow runtime 与 TriggerSource HTTP 控制面的 SDK client。
/// </summary>
public sealed class AmvisionWorkflowClient : IDisposable
{
    private const string WorkflowApiPrefix = "api/v1/workflows";

    private static readonly JsonSerializerOptions JsonOptions = new JsonSerializerOptions
    {
        DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull,
        PropertyNamingPolicy = null,
        WriteIndented = false
    };

    private readonly AmvisionWorkflowClientOptions options;
    private readonly HttpClient httpClient;
    private readonly bool ownsHttpClient;
    private bool disposed;

    /// <summary>
    /// 使用 SDK 自建 HttpClient 初始化控制面 client。
    /// </summary>
    /// <param name="options">HTTP 控制面参数。</param>
    public AmvisionWorkflowClient(AmvisionWorkflowClientOptions options)
    {
        this.options = options ?? throw new ArgumentNullException(nameof(options));
        this.options.Validate();
        httpClient = new HttpClient
        {
            BaseAddress = new Uri(NormalizeBaseApiUrl(this.options.BaseApiUrl), UriKind.Absolute),
            Timeout = this.options.Timeout
        };
        ownsHttpClient = true;
    }

    /// <summary>
    /// 使用外部提供的 HttpClient 初始化控制面 client。
    /// </summary>
    /// <param name="options">HTTP 控制面参数。</param>
    /// <param name="httpClient">外部提供的 HttpClient。</param>
    public AmvisionWorkflowClient(AmvisionWorkflowClientOptions options, HttpClient httpClient)
    {
        this.options = options ?? throw new ArgumentNullException(nameof(options));
        this.options.Validate();
        this.httpClient = httpClient ?? throw new ArgumentNullException(nameof(httpClient));
        if (this.httpClient.BaseAddress is null)
        {
            this.httpClient.BaseAddress = new Uri(NormalizeBaseApiUrl(this.options.BaseApiUrl), UriKind.Absolute);
        }

        ownsHttpClient = false;
    }

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
    /// 创建 WorkflowAppRuntime，并返回 typed contract。
    /// </summary>
    public async Task<WorkflowAppRuntimeContract> CreateWorkflowAppRuntimeContractAsync(
        WorkflowAppRuntimeCreateRequest request,
        CancellationToken cancellationToken = default)
    {
        return ReadJson<WorkflowAppRuntimeContract>(await CreateWorkflowAppRuntimeAsync(request, cancellationToken).ConfigureAwait(false));
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
    /// 按 Project id 列出 WorkflowAppRuntime，并返回 typed contracts。
    /// </summary>
    public async Task<IReadOnlyList<WorkflowAppRuntimeContract>> ListWorkflowAppRuntimeContractsAsync(
        string projectId,
        int offset = 0,
        int limit = 100,
        CancellationToken cancellationToken = default)
    {
        return ReadJsonList<WorkflowAppRuntimeContract>(
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
    /// 读取一条 WorkflowAppRuntime，并返回 typed contract。
    /// </summary>
    public async Task<WorkflowAppRuntimeContract> GetWorkflowAppRuntimeContractAsync(
        string workflowRuntimeId,
        CancellationToken cancellationToken = default)
    {
        return ReadJson<WorkflowAppRuntimeContract>(
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
    /// 读取 WorkflowAppRuntime 事件，并返回 typed contracts。
    /// </summary>
    public async Task<IReadOnlyList<WorkflowAppRuntimeEventContract>> GetWorkflowAppRuntimeEventContractsAsync(
        string workflowRuntimeId,
        long? afterSequence = null,
        int? limit = null,
        CancellationToken cancellationToken = default)
    {
        return ReadJsonList<WorkflowAppRuntimeEventContract>(
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
    /// 启动一个 WorkflowAppRuntime，并返回 typed contract。
    /// </summary>
    public async Task<WorkflowAppRuntimeContract> StartWorkflowAppRuntimeContractAsync(
        string workflowRuntimeId,
        CancellationToken cancellationToken = default)
    {
        return ReadJson<WorkflowAppRuntimeContract>(
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
    /// 停止一个 WorkflowAppRuntime，并返回 typed contract。
    /// </summary>
    public async Task<WorkflowAppRuntimeContract> StopWorkflowAppRuntimeContractAsync(
        string workflowRuntimeId,
        CancellationToken cancellationToken = default)
    {
        return ReadJson<WorkflowAppRuntimeContract>(
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
    /// 重启一个 WorkflowAppRuntime，并返回 typed contract。
    /// </summary>
    public async Task<WorkflowAppRuntimeContract> RestartWorkflowAppRuntimeContractAsync(
        string workflowRuntimeId,
        CancellationToken cancellationToken = default)
    {
        return ReadJson<WorkflowAppRuntimeContract>(
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
    /// 查询一个 WorkflowAppRuntime 的当前 health，并返回 typed contract。
    /// </summary>
    public async Task<WorkflowAppRuntimeContract> GetWorkflowAppRuntimeHealthContractAsync(
        string workflowRuntimeId,
        CancellationToken cancellationToken = default)
    {
        return ReadJson<WorkflowAppRuntimeContract>(
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
    /// 列出一个 WorkflowAppRuntime 的 worker instances，并返回 typed contracts。
    /// </summary>
    public async Task<IReadOnlyList<WorkflowAppRuntimeInstanceContract>> ListWorkflowAppRuntimeInstanceContractsAsync(
        string workflowRuntimeId,
        CancellationToken cancellationToken = default)
    {
        return ReadJsonList<WorkflowAppRuntimeInstanceContract>(
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
    /// 创建一条异步 WorkflowRun，并返回 typed contract。
    /// </summary>
    public async Task<WorkflowRunContract> CreateWorkflowRunContractAsync(
        string workflowRuntimeId,
        WorkflowRuntimeInvokeRequest request,
        CancellationToken cancellationToken = default)
    {
        return ReadJson<WorkflowRunContract>(
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
    /// 通过通用 JSON 请求调用 WorkflowAppRuntime，并返回 WorkflowRun typed contract。
    /// </summary>
    public async Task<WorkflowRunContract> InvokeWorkflowAppRuntimeContractAsync(
        string workflowRuntimeId,
        WorkflowRuntimeInvokeRequest request,
        string responseMode = WorkflowResponseModes.Run,
        CancellationToken cancellationToken = default)
    {
        return ReadJson<WorkflowRunContract>(
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
    /// 通过 image-base64.v1 方式调用 WorkflowAppRuntime，并返回 WorkflowRun typed contract。
    /// </summary>
    public async Task<WorkflowRunContract> InvokeWorkflowAppRuntimeWithImageBase64ContractAsync(
        string workflowRuntimeId,
        WorkflowRuntimeImageInvokeRequest request,
        string responseMode = WorkflowResponseModes.Run,
        CancellationToken cancellationToken = default)
    {
        return ReadJson<WorkflowRunContract>(
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
    /// 读取一条 WorkflowRun，并返回 typed contract。
    /// </summary>
    public async Task<WorkflowRunContract> GetWorkflowRunContractAsync(
        string workflowRunId,
        string responseMode = WorkflowResponseModes.Run,
        CancellationToken cancellationToken = default)
    {
        return ReadJson<WorkflowRunContract>(
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
    /// 读取 WorkflowRun 事件，并返回 typed contracts。
    /// </summary>
    public async Task<IReadOnlyList<WorkflowRunEventContract>> GetWorkflowRunEventContractsAsync(
        string workflowRunId,
        long? afterSequence = null,
        int? limit = null,
        CancellationToken cancellationToken = default)
    {
        return ReadJsonList<WorkflowRunEventContract>(
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
    /// 取消一条异步 WorkflowRun，并返回 typed contract。
    /// </summary>
    public async Task<WorkflowRunContract> CancelWorkflowRunContractAsync(
        string workflowRunId,
        CancellationToken cancellationToken = default)
    {
        return ReadJson<WorkflowRunContract>(
            await CancelWorkflowRunAsync(workflowRunId, cancellationToken).ConfigureAwait(false));
    }

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
    /// 按 Project id 列出 TriggerSource，并返回 typed contracts。
    /// </summary>
    public async Task<IReadOnlyList<WorkflowTriggerSourceContract>> ListTriggerSourceContractsAsync(
        string projectId,
        int offset = 0,
        int limit = 100,
        CancellationToken cancellationToken = default)
    {
        return ReadJsonList<WorkflowTriggerSourceContract>(
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
    /// 读取一条 TriggerSource，并返回 typed contract。
    /// </summary>
    public async Task<WorkflowTriggerSourceContract> GetTriggerSourceContractAsync(
        string triggerSourceId,
        CancellationToken cancellationToken = default)
    {
        return ReadJson<WorkflowTriggerSourceContract>(
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
    /// 创建一条 TriggerSource，并返回 typed contract。
    /// </summary>
    public async Task<WorkflowTriggerSourceContract> CreateTriggerSourceContractAsync(
        WorkflowTriggerSourceCreateRequest request,
        CancellationToken cancellationToken = default)
    {
        return ReadJson<WorkflowTriggerSourceContract>(
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
    /// 启用一条 TriggerSource，并返回 typed contract。
    /// </summary>
    public async Task<WorkflowTriggerSourceContract> EnableTriggerSourceContractAsync(
        string triggerSourceId,
        CancellationToken cancellationToken = default)
    {
        return ReadJson<WorkflowTriggerSourceContract>(
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
    /// 停用一条 TriggerSource，并返回 typed contract。
    /// </summary>
    public async Task<WorkflowTriggerSourceContract> DisableTriggerSourceContractAsync(
        string triggerSourceId,
        CancellationToken cancellationToken = default)
    {
        return ReadJson<WorkflowTriggerSourceContract>(
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
    /// 查询一条 TriggerSource 的当前 health，并返回 typed contract。
    /// </summary>
    public async Task<WorkflowTriggerSourceHealthContract> GetTriggerSourceHealthContractAsync(
        string triggerSourceId,
        CancellationToken cancellationToken = default)
    {
        return ReadJson<WorkflowTriggerSourceHealthContract>(
            await GetTriggerSourceHealthAsync(triggerSourceId, cancellationToken).ConfigureAwait(false));
    }

    /// <summary>
    /// 释放 SDK 内部持有的 HttpClient。
    /// </summary>
    public void Dispose()
    {
        if (disposed)
        {
            return;
        }

        if (ownsHttpClient)
        {
            httpClient.Dispose();
        }

        disposed = true;
    }

    /// <summary>
    /// 发送一条 HTTP 控制面请求。
    /// </summary>
    private async Task<AmvisionWorkflowApiResponse> SendAsync(
        HttpMethod method,
        string relativePath,
        string? content,
        CancellationToken cancellationToken)
    {
        if (disposed)
        {
            throw new ObjectDisposedException(nameof(AmvisionWorkflowClient));
        }

        using var request = new HttpRequestMessage(method, relativePath);
        request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", options.AccessToken.Trim());
        if (content is not null)
        {
            request.Content = new StringContent(content, Encoding.UTF8, "application/json");
        }

        using var response = await httpClient.SendAsync(request, cancellationToken).ConfigureAwait(false);
        var responseText = response.Content is null
            ? string.Empty
            : await response.Content.ReadAsStringAsync().ConfigureAwait(false);
        return AmvisionWorkflowApiResponse.Create(response.StatusCode, responseText);
    }

    /// <summary>
    /// 序列化 JSON 请求体。
    /// </summary>
    private static string SerializeJson<T>(T payload)
    {
        if (payload is null)
        {
            throw new ArgumentNullException(nameof(payload));
        }
        return JsonSerializer.Serialize(payload, JsonOptions);
    }

    /// <summary>
    /// 读取 typed JSON 响应。
    /// </summary>
    private static T ReadJson<T>(AmvisionWorkflowApiResponse response)
    {
        return response.ReadJson<T>(JsonOptions);
    }

    /// <summary>
    /// 读取 typed JSON 数组响应。
    /// </summary>
    private static IReadOnlyList<T> ReadJsonList<T>(AmvisionWorkflowApiResponse response)
    {
        return response.ReadJson<List<T>>(JsonOptions);
    }

    /// <summary>
    /// 规范化 base API URL，确保结尾带斜杠。
    /// </summary>
    private static string NormalizeBaseApiUrl(string baseApiUrl)
    {
        var trimmed = baseApiUrl.Trim();
        return trimmed.EndsWith("/", StringComparison.Ordinal) ? trimmed : $"{trimmed}/";
    }

    /// <summary>
    /// 拼接 query string。
    /// </summary>
    private static string WithQuery(string relativePath, params (string Name, object? Value)[] query)
    {
        var items = new List<string>();
        foreach (var (name, value) in query)
        {
            if (value is null)
            {
                continue;
            }

            var text = Convert.ToString(value, CultureInfo.InvariantCulture);
            if (string.IsNullOrWhiteSpace(text))
            {
                continue;
            }

            items.Add($"{Uri.EscapeDataString(name)}={Uri.EscapeDataString(text)}");
        }

        return items.Count == 0 ? relativePath : $"{relativePath}?{string.Join("&", items)}";
    }

    /// <summary>
    /// 校验 id 字段非空。
    /// </summary>
    private static string RequireId(string value, string paramName)
    {
        if (string.IsNullOrWhiteSpace(value))
        {
            throw new ArgumentException($"{paramName} cannot be empty.", paramName);
        }

        return value.Trim();
    }

    /// <summary>
    /// 对路径片段做 URL 编码。
    /// </summary>
    private static string EncodePathSegment(string value)
    {
        return Uri.EscapeDataString(value);
    }
}
