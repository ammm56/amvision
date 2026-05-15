using System;
using System.Net.Http;
using System.Net.Http.Headers;
using System.Text;
using System.Threading;
using System.Threading.Tasks;

namespace Amvision.TriggerSources;

/// <summary>
/// backend-service Workflow runtime 与 TriggerSource HTTP 控制面的 SDK client。
/// </summary>
public sealed class AmvisionWorkflowClient : IDisposable
{
    private const string WorkflowApiPrefix = "api/v1/workflows";

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
    /// 启动一个 WorkflowAppRuntime。
    /// </summary>
    /// <param name="workflowRuntimeId">目标 runtime id。</param>
    /// <param name="cancellationToken">取消令牌。</param>
    /// <returns>控制面响应。</returns>
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
    /// 停止一个 WorkflowAppRuntime。
    /// </summary>
    /// <param name="workflowRuntimeId">目标 runtime id。</param>
    /// <param name="cancellationToken">取消令牌。</param>
    /// <returns>控制面响应。</returns>
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
    /// 查询一个 WorkflowAppRuntime 的当前 health。
    /// </summary>
    /// <param name="workflowRuntimeId">目标 runtime id。</param>
    /// <param name="cancellationToken">取消令牌。</param>
    /// <returns>控制面响应。</returns>
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
    /// 通过通用 JSON 请求调用 WorkflowAppRuntime。
    /// </summary>
    /// <param name="workflowRuntimeId">目标 runtime id。</param>
    /// <param name="request">invoke 请求对象。</param>
    /// <param name="cancellationToken">取消令牌。</param>
    /// <returns>控制面响应。</returns>
    public Task<AmvisionWorkflowApiResponse> InvokeWorkflowAppRuntimeAsync(
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
            $"{WorkflowApiPrefix}/app-runtimes/{EncodePathSegment(RequireId(workflowRuntimeId, nameof(workflowRuntimeId)))}/invoke",
            request.ToJson(),
            cancellationToken);
    }

    /// <summary>
    /// 通过 image-base64.v1 方式调用 WorkflowAppRuntime。
    /// </summary>
    /// <param name="workflowRuntimeId">目标 runtime id。</param>
    /// <param name="request">图片 invoke 请求。</param>
    /// <param name="cancellationToken">取消令牌。</param>
    /// <returns>控制面响应。</returns>
    public Task<AmvisionWorkflowApiResponse> InvokeWorkflowAppRuntimeWithImageBase64Async(
        string workflowRuntimeId,
        WorkflowRuntimeImageInvokeRequest request,
        CancellationToken cancellationToken = default)
    {
        if (request is null)
        {
            throw new ArgumentNullException(nameof(request));
        }

        return InvokeWorkflowAppRuntimeAsync(
            workflowRuntimeId,
            request.ToWorkflowRuntimeInvokeRequest(),
            cancellationToken);
    }

    /// <summary>
    /// 读取一条 WorkflowRun。
    /// </summary>
    /// <param name="workflowRunId">目标 WorkflowRun id。</param>
    /// <param name="cancellationToken">取消令牌。</param>
    /// <returns>控制面响应。</returns>
    public Task<AmvisionWorkflowApiResponse> GetWorkflowRunAsync(
        string workflowRunId,
        CancellationToken cancellationToken = default)
    {
        return SendAsync(
            HttpMethod.Get,
            $"{WorkflowApiPrefix}/runs/{EncodePathSegment(RequireId(workflowRunId, nameof(workflowRunId)))}",
            content: null,
            cancellationToken);
    }

    /// <summary>
    /// 启用一条 TriggerSource。
    /// </summary>
    /// <param name="triggerSourceId">目标 TriggerSource id。</param>
    /// <param name="cancellationToken">取消令牌。</param>
    /// <returns>控制面响应。</returns>
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
    /// 停用一条 TriggerSource。
    /// </summary>
    /// <param name="triggerSourceId">目标 TriggerSource id。</param>
    /// <param name="cancellationToken">取消令牌。</param>
    /// <returns>控制面响应。</returns>
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
    /// 查询一条 TriggerSource 的当前 health。
    /// </summary>
    /// <param name="triggerSourceId">目标 TriggerSource id。</param>
    /// <param name="cancellationToken">取消令牌。</param>
    /// <returns>控制面响应。</returns>
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
    /// <param name="method">HTTP 方法。</param>
    /// <param name="relativePath">相对路径。</param>
    /// <param name="content">可选 JSON 请求体。</param>
    /// <param name="cancellationToken">取消令牌。</param>
    /// <returns>控制面响应。</returns>
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
    /// 规范化 base API URL，确保结尾带斜杠。
    /// </summary>
    /// <param name="baseApiUrl">原始 base URL。</param>
    /// <returns>规范化后的 base URL。</returns>
    private static string NormalizeBaseApiUrl(string baseApiUrl)
    {
        var trimmed = baseApiUrl.Trim();
        return trimmed.EndsWith("/", StringComparison.Ordinal) ? trimmed : $"{trimmed}/";
    }

    /// <summary>
    /// 校验 id 字段非空。
    /// </summary>
    /// <param name="value">原始 id。</param>
    /// <param name="paramName">参数名。</param>
    /// <returns>去空白后的 id。</returns>
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
    /// <param name="value">原始片段。</param>
    /// <returns>编码后的片段。</returns>
    private static string EncodePathSegment(string value)
    {
        return Uri.EscapeDataString(value);
    }
}