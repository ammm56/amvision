using System;
using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;
using Amvision.Workflows;
using Amvision.Workflows.Console.Model;
using Amvision.Workflows.Console.Runtime;
using Amvision.Workflows.Console.TriggerSource;
using Amvision.Workflows.Console.TriggerSource.ZeroMQ;
using Amvision.Workflows.Console.Tools;

namespace Amvision.Workflows.Console;

/// <summary>
/// 面向现场程序的 Workflow 调用入口，把底层 SDK 和配置读取再次封装为可直接调用的方法。
/// </summary>
public sealed class WorkflowOperationRunner : IDisposable
{
    /// <summary>
    /// 启动时载入的配置索引，所有方法调用前都会用它校验 key 是否存在。
    /// </summary>
    private readonly WorkflowConfigurationCatalog catalog;

    /// <summary>
    /// 复用的 HTTP SDK client。
    /// </summary>
    private readonly AmvisionWorkflowClient workflowClient;

    /// <summary>
    /// WorkflowAppRuntime 控制和调用封装。
    /// </summary>
    private readonly WorkflowRuntimeOperations runtimeOperations;

    /// <summary>
    /// TriggerSource HTTP 控制封装。
    /// </summary>
    private readonly WorkflowTriggerSourceOperations triggerSourceOperations;

    /// <summary>
    /// ZeroMQ TriggerSource 协议调用封装。
    /// </summary>
    private readonly ZeroMqTriggerOperations zeroMqOperations;

    /// <summary>
    /// 构造一个可复用的 Workflow 调用入口。
    /// </summary>
    /// <param name="catalog">已经校验过的配置索引。</param>
    internal WorkflowOperationRunner(WorkflowConfigurationCatalog catalog)
    {
        this.catalog = catalog ?? throw new ArgumentNullException(nameof(catalog));
        workflowClient = new AmvisionWorkflowClient(new AmvisionWorkflowClientOptions
        {
            BaseApiUrl = catalog.DefaultBackend.BaseApiUrl,
            AccessToken = catalog.DefaultBackend.AccessToken,
            Timeout = TimeSpan.FromSeconds(catalog.DefaultBackend.HttpTimeoutSeconds)
        });
        runtimeOperations = new WorkflowRuntimeOperations(workflowClient, catalog);
        triggerSourceOperations = new WorkflowTriggerSourceOperations(workflowClient, catalog);
        zeroMqOperations = new ZeroMqTriggerOperations(catalog);
    }

    /// <summary>
    /// 从默认 Config 目录加载配置并创建 Workflow 调用入口。
    /// </summary>
    /// <returns>可直接调用的 WorkflowOperationRunner。</returns>
    public static WorkflowOperationRunner CreateDefault()
    {
        var catalog = WorkflowConfigLoader.LoadDefault();
        WorkflowConfigStore.Initialize(catalog);
        return new WorkflowOperationRunner(catalog);
    }

    /// <summary>
    /// 获取配置中的 runtime key 列表，便于图形界面绑定下拉框。
    /// </summary>
    public IEnumerable<string> RuntimeNames => catalog.Runtimes.Keys;

    /// <summary>
    /// 获取配置中的 TriggerSource key 列表，便于图形界面绑定下拉框。
    /// </summary>
    public IEnumerable<string> TriggerSourceNames => catalog.TriggerSources.Keys;

    /// <summary>
    /// 释放内部 HTTP client 和 ZeroMQ client。
    /// </summary>
    public void Dispose()
    {
        zeroMqOperations.Dispose();
        workflowClient.Dispose();
    }

    /// <summary>
    /// 列出当前 Project 下的 WorkflowAppRuntime。
    /// </summary>
    /// <param name="runtimeName">runtime 配置 key。</param>
    /// <param name="cancellationToken">取消信号。</param>
    /// <returns>runtime 列表。</returns>
    public Task<IReadOnlyList<WorkflowAppRuntimeResponse>> ListProjectRuntimesAsync(
        string runtimeName,
        CancellationToken cancellationToken = default)
    {
        RequireRuntime(runtimeName);
        return runtimeOperations.ListProjectRuntimesAsync(runtimeName, cancellationToken);
    }

    /// <summary>
    /// 读取一个已存在的 WorkflowAppRuntime。
    /// </summary>
    /// <param name="runtimeName">runtime 配置 key。</param>
    /// <param name="cancellationToken">取消信号。</param>
    /// <returns>runtime 响应。</returns>
    public Task<WorkflowAppRuntimeResponse> GetRuntimeAsync(
        string runtimeName,
        CancellationToken cancellationToken = default)
    {
        RequireRuntime(runtimeName);
        return runtimeOperations.GetRuntimeAsync(runtimeName, cancellationToken);
    }

    /// <summary>
    /// 启动一个已存在的 WorkflowAppRuntime。
    /// </summary>
    /// <param name="runtimeName">runtime 配置 key。</param>
    /// <param name="cancellationToken">取消信号。</param>
    /// <returns>runtime 响应。</returns>
    public Task<WorkflowAppRuntimeResponse> StartRuntimeAsync(
        string runtimeName,
        CancellationToken cancellationToken = default)
    {
        RequireRuntime(runtimeName);
        return runtimeOperations.StartRuntimeAsync(runtimeName, cancellationToken);
    }

    /// <summary>
    /// 停止一个已存在的 WorkflowAppRuntime。
    /// </summary>
    /// <param name="runtimeName">runtime 配置 key。</param>
    /// <param name="cancellationToken">取消信号。</param>
    /// <returns>runtime 响应。</returns>
    public Task<WorkflowAppRuntimeResponse> StopRuntimeAsync(
        string runtimeName,
        CancellationToken cancellationToken = default)
    {
        RequireRuntime(runtimeName);
        return runtimeOperations.StopRuntimeAsync(runtimeName, cancellationToken);
    }

    /// <summary>
    /// 重启一个已存在的 WorkflowAppRuntime。
    /// </summary>
    /// <param name="runtimeName">runtime 配置 key。</param>
    /// <param name="cancellationToken">取消信号。</param>
    /// <returns>runtime 响应。</returns>
    public Task<WorkflowAppRuntimeResponse> RestartRuntimeAsync(
        string runtimeName,
        CancellationToken cancellationToken = default)
    {
        RequireRuntime(runtimeName);
        return runtimeOperations.RestartRuntimeAsync(runtimeName, cancellationToken);
    }

    /// <summary>
    /// 读取 WorkflowAppRuntime health。
    /// </summary>
    /// <param name="runtimeName">runtime 配置 key。</param>
    /// <param name="cancellationToken">取消信号。</param>
    /// <returns>runtime health 响应。</returns>
    public Task<WorkflowAppRuntimeResponse> GetRuntimeHealthAsync(
        string runtimeName,
        CancellationToken cancellationToken = default)
    {
        RequireRuntime(runtimeName);
        return runtimeOperations.GetRuntimeHealthAsync(runtimeName, cancellationToken);
    }

    /// <summary>
    /// 列出 WorkflowAppRuntime 实例。
    /// </summary>
    /// <param name="runtimeName">runtime 配置 key。</param>
    /// <param name="cancellationToken">取消信号。</param>
    /// <returns>runtime instance 列表。</returns>
    public Task<IReadOnlyList<WorkflowAppRuntimeInstanceResponse>> ListRuntimeInstancesAsync(
        string runtimeName,
        CancellationToken cancellationToken = default)
    {
        RequireRuntime(runtimeName);
        return runtimeOperations.ListRuntimeInstancesAsync(runtimeName, cancellationToken);
    }

    /// <summary>
    /// 同步调用 WorkflowAppRuntime，并直接读取 app-result。
    /// </summary>
    /// <param name="runtimeName">runtime 配置 key。</param>
    /// <param name="cancellationToken">取消信号。</param>
    /// <returns>app-result 响应。</returns>
    public Task<WorkflowAppResultResponse> InvokeRuntimeAppResultAsync(
        string runtimeName,
        CancellationToken cancellationToken = default)
    {
        RequireRuntime(runtimeName);
        return runtimeOperations.InvokeRuntimeAppResultAsync(runtimeName, cancellationToken);
    }

    /// <summary>
    /// 异步调用 WorkflowAppRuntime，后端会创建一条 WorkflowRun。
    /// </summary>
    /// <param name="runtimeName">runtime 配置 key。</param>
    /// <param name="cancellationToken">取消信号。</param>
    /// <returns>WorkflowRun 响应。</returns>
    public Task<WorkflowRunResponse> RunRuntimeAsync(
        string runtimeName,
        CancellationToken cancellationToken = default)
    {
        RequireRuntime(runtimeName);
        return runtimeOperations.RunRuntimeAsync(runtimeName, cancellationToken);
    }

    /// <summary>
    /// 使用 base64 图片同步调用 WorkflowAppRuntime，并直接读取 app-result。
    /// </summary>
    /// <param name="runtimeName">runtime 配置 key。</param>
    /// <param name="imageBase64">图片 base64 或 data URL。</param>
    /// <param name="mediaType">可选 media type；data URL 会优先使用自身声明。</param>
    /// <param name="cancellationToken">取消信号。</param>
    /// <returns>app-result 响应。</returns>
    public Task<WorkflowAppResultResponse> InvokeRuntimeAppResultWithImageBase64Async(
        string runtimeName,
        string imageBase64,
        string? mediaType = null,
        CancellationToken cancellationToken = default)
    {
        RequireRuntime(runtimeName);
        return runtimeOperations.InvokeRuntimeAppResultWithImageBase64Async(
            runtimeName,
            imageBase64,
            mediaType,
            cancellationToken);
    }

    /// <summary>
    /// 使用图片 bytes 同步调用 WorkflowAppRuntime，并直接读取 app-result。
    /// </summary>
    /// <param name="runtimeName">runtime 配置 key。</param>
    /// <param name="imageBytes">图片编码 bytes，通常来自工业相机 SDK 或内存缓存。</param>
    /// <param name="mediaType">media type。</param>
    /// <param name="cancellationToken">取消信号。</param>
    /// <returns>app-result 响应。</returns>
    public Task<WorkflowAppResultResponse> InvokeRuntimeAppResultWithImageBytesAsync(
        string runtimeName,
        byte[] imageBytes,
        string mediaType = "image/octet-stream",
        CancellationToken cancellationToken = default)
    {
        RequireRuntime(runtimeName);
        return runtimeOperations.InvokeRuntimeAppResultWithImageBytesAsync(
            runtimeName,
            imageBytes,
            mediaType,
            cancellationToken);
    }

    /// <summary>
    /// 使用图片文件路径同步调用 WorkflowAppRuntime，并直接读取 app-result。
    /// </summary>
    /// <param name="runtimeName">runtime 配置 key。</param>
    /// <param name="imagePath">图片文件路径。</param>
    /// <param name="mediaType">可选 media type；为空时按扩展名推断。</param>
    /// <param name="cancellationToken">取消信号。</param>
    /// <returns>app-result 响应。</returns>
    public Task<WorkflowAppResultResponse> InvokeRuntimeAppResultWithImageFromFileAsync(
        string runtimeName,
        string imagePath,
        string? mediaType = null,
        CancellationToken cancellationToken = default)
    {
        RequireRuntime(runtimeName);
        return runtimeOperations.InvokeRuntimeAppResultWithImageFromFileAsync(
            runtimeName,
            imagePath,
            mediaType,
            cancellationToken);
    }

    /// <summary>
    /// 使用 base64 图片异步调用 WorkflowAppRuntime，后端会创建一条 WorkflowRun。
    /// </summary>
    /// <param name="runtimeName">runtime 配置 key。</param>
    /// <param name="imageBase64">图片 base64 或 data URL。</param>
    /// <param name="mediaType">可选 media type；data URL 会优先使用自身声明。</param>
    /// <param name="cancellationToken">取消信号。</param>
    /// <returns>WorkflowRun 响应。</returns>
    public Task<WorkflowRunResponse> RunRuntimeWithImageBase64Async(
        string runtimeName,
        string imageBase64,
        string? mediaType = null,
        CancellationToken cancellationToken = default)
    {
        RequireRuntime(runtimeName);
        return runtimeOperations.RunRuntimeWithImageBase64Async(
            runtimeName,
            imageBase64,
            mediaType,
            cancellationToken);
    }

    /// <summary>
    /// 使用图片 bytes 异步调用 WorkflowAppRuntime，后端会创建一条 WorkflowRun。
    /// </summary>
    /// <param name="runtimeName">runtime 配置 key。</param>
    /// <param name="imageBytes">图片编码 bytes，通常来自工业相机 SDK 或内存缓存。</param>
    /// <param name="mediaType">media type。</param>
    /// <param name="cancellationToken">取消信号。</param>
    /// <returns>WorkflowRun 响应。</returns>
    public Task<WorkflowRunResponse> RunRuntimeWithImageBytesAsync(
        string runtimeName,
        byte[] imageBytes,
        string mediaType = "image/octet-stream",
        CancellationToken cancellationToken = default)
    {
        RequireRuntime(runtimeName);
        return runtimeOperations.RunRuntimeWithImageBytesAsync(
            runtimeName,
            imageBytes,
            mediaType,
            cancellationToken);
    }

    /// <summary>
    /// 使用图片文件路径异步调用 WorkflowAppRuntime，后端会创建一条 WorkflowRun。
    /// </summary>
    /// <param name="runtimeName">runtime 配置 key。</param>
    /// <param name="imagePath">图片文件路径。</param>
    /// <param name="mediaType">可选 media type；为空时按扩展名推断。</param>
    /// <param name="cancellationToken">取消信号。</param>
    /// <returns>WorkflowRun 响应。</returns>
    public Task<WorkflowRunResponse> RunRuntimeWithImageFromFileAsync(
        string runtimeName,
        string imagePath,
        string? mediaType = null,
        CancellationToken cancellationToken = default)
    {
        RequireRuntime(runtimeName);
        return runtimeOperations.RunRuntimeWithImageFromFileAsync(
            runtimeName,
            imagePath,
            mediaType,
            cancellationToken);
    }

    /// <summary>
    /// 执行 runtime 调用链检查，包含 health、instances、同步 invoke、异步 run 和事件查询。
    /// </summary>
    /// <param name="runtimeName">runtime 配置 key。</param>
    /// <param name="cancellationToken">取消信号。</param>
    /// <returns>调用链检查结果。</returns>
    public Task<RuntimeFlowCheckResult> CheckRuntimeFlowAsync(
        string runtimeName,
        CancellationToken cancellationToken = default)
    {
        RequireRuntime(runtimeName);
        return runtimeOperations.CheckRuntimeFlowAsync(runtimeName, cancellationToken);
    }

    /// <summary>
    /// 读取 WorkflowAppRuntime 事件。
    /// </summary>
    /// <param name="runtimeName">runtime 配置 key。</param>
    /// <param name="cancellationToken">取消信号。</param>
    /// <returns>runtime 事件列表。</returns>
    public Task<IReadOnlyList<WorkflowAppRuntimeEventResponse>> GetRuntimeEventsAsync(
        string runtimeName,
        CancellationToken cancellationToken = default)
    {
        RequireRuntime(runtimeName);
        return runtimeOperations.GetRuntimeEventsAsync(runtimeName, cancellationToken);
    }

    /// <summary>
    /// 按 workflow_run_id 读取 WorkflowRun。
    /// </summary>
    /// <param name="workflowRunId">WorkflowRun id。</param>
    /// <param name="cancellationToken">取消信号。</param>
    /// <returns>WorkflowRun 响应。</returns>
    public Task<WorkflowRunResponse> GetWorkflowRunAsync(
        string workflowRunId,
        CancellationToken cancellationToken = default)
    {
        return runtimeOperations.GetWorkflowRunAsync(workflowRunId, cancellationToken);
    }

    /// <summary>
    /// 读取 WorkflowRun 事件。
    /// </summary>
    /// <param name="runtimeName">runtime 配置 key，用于读取事件输出条数配置。</param>
    /// <param name="workflowRunId">WorkflowRun id。</param>
    /// <param name="cancellationToken">取消信号。</param>
    /// <returns>WorkflowRun 事件列表。</returns>
    public Task<IReadOnlyList<WorkflowRunEventResponse>> GetWorkflowRunEventsAsync(
        string runtimeName,
        string workflowRunId,
        CancellationToken cancellationToken = default)
    {
        RequireRuntime(runtimeName);
        return runtimeOperations.GetWorkflowRunEventsAsync(runtimeName, workflowRunId, cancellationToken);
    }

    /// <summary>
    /// 列出当前 Project 下的 TriggerSource。
    /// </summary>
    /// <param name="runtimeName">runtime 配置 key，用于读取 Project id。</param>
    /// <param name="cancellationToken">取消信号。</param>
    /// <returns>TriggerSource 列表。</returns>
    public Task<IReadOnlyList<WorkflowTriggerSourceResponse>> ListTriggerSourcesAsync(
        string runtimeName,
        CancellationToken cancellationToken = default)
    {
        RequireRuntime(runtimeName);
        return triggerSourceOperations.ListTriggerSourcesAsync(runtimeName, cancellationToken);
    }

    /// <summary>
    /// 读取一个已存在的 TriggerSource。
    /// </summary>
    /// <param name="triggerSourceName">TriggerSource 配置 key。</param>
    /// <param name="cancellationToken">取消信号。</param>
    /// <returns>TriggerSource 响应。</returns>
    public Task<WorkflowTriggerSourceResponse> GetTriggerSourceAsync(
        string triggerSourceName,
        CancellationToken cancellationToken = default)
    {
        RequireTriggerSource(triggerSourceName);
        return triggerSourceOperations.GetTriggerSourceAsync(triggerSourceName, cancellationToken);
    }

    /// <summary>
    /// 启用一个已存在的 TriggerSource。
    /// </summary>
    /// <param name="triggerSourceName">TriggerSource 配置 key。</param>
    /// <param name="cancellationToken">取消信号。</param>
    /// <returns>TriggerSource 响应。</returns>
    public Task<WorkflowTriggerSourceResponse> EnableTriggerSourceAsync(
        string triggerSourceName,
        CancellationToken cancellationToken = default)
    {
        RequireTriggerSource(triggerSourceName);
        return triggerSourceOperations.EnableTriggerSourceAsync(triggerSourceName, cancellationToken);
    }

    /// <summary>
    /// 停用一个已存在的 TriggerSource。
    /// </summary>
    /// <param name="triggerSourceName">TriggerSource 配置 key。</param>
    /// <param name="cancellationToken">取消信号。</param>
    /// <returns>TriggerSource 响应。</returns>
    public Task<WorkflowTriggerSourceResponse> DisableTriggerSourceAsync(
        string triggerSourceName,
        CancellationToken cancellationToken = default)
    {
        RequireTriggerSource(triggerSourceName);
        return triggerSourceOperations.DisableTriggerSourceAsync(triggerSourceName, cancellationToken);
    }

    /// <summary>
    /// 读取 TriggerSource health。
    /// </summary>
    /// <param name="triggerSourceName">TriggerSource 配置 key。</param>
    /// <param name="cancellationToken">取消信号。</param>
    /// <returns>TriggerSource health 响应。</returns>
    public Task<WorkflowTriggerSourceHealthResponse> GetTriggerSourceHealthAsync(
        string triggerSourceName,
        CancellationToken cancellationToken = default)
    {
        RequireTriggerSource(triggerSourceName);
        return triggerSourceOperations.GetTriggerSourceHealthAsync(triggerSourceName, cancellationToken);
    }

    /// <summary>
    /// 使用 ZeroMQ 发送纯事件触发，不携带图片第二帧。
    /// </summary>
    /// <param name="triggerSourceName">TriggerSource 配置 key。</param>
    /// <param name="payload">事件 payload；为空时发送空事件。</param>
    /// <param name="cancellationToken">取消信号。</param>
    /// <returns>TriggerSource 调用结果。</returns>
    public Task<TriggerResult> InvokeZeroMqEventAsync(
        string triggerSourceName,
        IDictionary<string, object?>? payload = null,
        CancellationToken cancellationToken = default)
    {
        RequireTriggerSource(triggerSourceName);
        return zeroMqOperations.InvokeEventAsync(triggerSourceName, payload, cancellationToken);
    }

    /// <summary>
    /// 使用配置中的图片路径执行 ZeroMQ 图片触发。
    /// </summary>
    /// <param name="triggerSourceName">TriggerSource 配置 key。</param>
    /// <param name="cancellationToken">取消信号。</param>
    /// <returns>TriggerSource 调用结果。</returns>
    public Task<TriggerResult> InvokeZeroMqConfiguredImageAsync(
        string triggerSourceName,
        CancellationToken cancellationToken = default)
    {
        RequireTriggerSource(triggerSourceName);
        return zeroMqOperations.InvokeConfiguredImageAsync(triggerSourceName, cancellationToken);
    }

    /// <summary>
    /// 从磁盘图片文件执行 ZeroMQ 图片触发。
    /// </summary>
    /// <param name="triggerSourceName">TriggerSource 配置 key。</param>
    /// <param name="imagePath">图片路径。</param>
    /// <param name="mediaType">可选 media type。</param>
    /// <param name="cancellationToken">取消信号。</param>
    /// <returns>TriggerSource 调用结果。</returns>
    public Task<TriggerResult> InvokeZeroMqImageFromFileAsync(
        string triggerSourceName,
        string imagePath,
        string? mediaType = null,
        CancellationToken cancellationToken = default)
    {
        RequireTriggerSource(triggerSourceName);
        return zeroMqOperations.InvokeImageFromFileAsync(triggerSourceName, imagePath, mediaType, cancellationToken);
    }

    /// <summary>
    /// 用图片 bytes 执行 ZeroMQ 图片触发。
    /// </summary>
    /// <param name="triggerSourceName">TriggerSource 配置 key。</param>
    /// <param name="imageBytes">图片编码 bytes。</param>
    /// <param name="mediaType">media type。</param>
    /// <param name="cancellationToken">取消信号。</param>
    /// <returns>TriggerSource 调用结果。</returns>
    public Task<TriggerResult> InvokeZeroMqImageBytesAsync(
        string triggerSourceName,
        byte[] imageBytes,
        string mediaType = "image/octet-stream",
        CancellationToken cancellationToken = default)
    {
        RequireTriggerSource(triggerSourceName);
        return zeroMqOperations.InvokeImageBytesAsync(triggerSourceName, imageBytes, mediaType, cancellationToken);
    }

    /// <summary>
    /// 用 base64 图片执行 ZeroMQ 图片触发，方法内部会转成 multipart 第二帧 bytes。
    /// </summary>
    /// <param name="triggerSourceName">TriggerSource 配置 key。</param>
    /// <param name="imageBase64">图片 base64 或 data URL。</param>
    /// <param name="mediaType">可选 media type。</param>
    /// <param name="cancellationToken">取消信号。</param>
    /// <returns>TriggerSource 调用结果。</returns>
    public Task<TriggerResult> InvokeZeroMqImageBase64Async(
        string triggerSourceName,
        string imageBase64,
        string? mediaType = null,
        CancellationToken cancellationToken = default)
    {
        RequireTriggerSource(triggerSourceName);
        return zeroMqOperations.InvokeImageBase64Async(triggerSourceName, imageBase64, mediaType, cancellationToken);
    }

    /// <summary>
    /// 获取 runtime 配置并校验 key 是否存在。
    /// </summary>
    /// <param name="runtimeName">runtime 配置 key。</param>
    /// <returns>runtime 配置。</returns>
    private ConfiguredRuntime RequireRuntime(string runtimeName)
    {
        return catalog.GetRuntime(runtimeName);
    }

    /// <summary>
    /// 获取 TriggerSource 配置并校验 key 是否存在。
    /// </summary>
    /// <param name="triggerSourceName">TriggerSource 配置 key。</param>
    /// <returns>TriggerSource 配置。</returns>
    private ConfiguredTriggerSource RequireTriggerSource(string triggerSourceName)
    {
        return catalog.GetTriggerSource(triggerSourceName);
    }
}
