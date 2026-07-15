using System;
using Amvision.Workflows;
using System.Threading;
using System.Threading.Tasks;

namespace Amvision.Workflows.Runtime
{
/// <summary>
/// WorkflowAppRuntime 同步调用操作。
/// </summary>
internal sealed partial class WorkflowRuntimeOperations
{
    /// <summary>
    /// 按 runtime key 执行同步 invoke，并按 app-result 模式读取结果。
    /// </summary>
    /// <param name="runtimeName">runtime key。</param>
    /// <param name="cancellationToken">取消信号。</param>
    /// <returns>app-result 响应。</returns>
    public async Task<WorkflowAppResultResponse> InvokeRuntimeAppResultAsync(
        string runtimeName,
        CancellationToken cancellationToken = default)
    {
        var configuredRuntime = GetConfiguredRuntime(runtimeName);
        var workflowRuntimeId = RequireRuntimeId(configuredRuntime);
        var appResult = HasImageInput(configuredRuntime)
            ? await client.InvokeWorkflowAppRuntimeWithImageBase64AppResultResponseAsync(
                workflowRuntimeId,
                BuildImageInvokeRequest(configuredRuntime, configuredRuntime.Invoke.SyncScenario),
                cancellationToken).ConfigureAwait(false)
            : await client.InvokeWorkflowAppRuntimeAppResultResponseAsync(
                workflowRuntimeId,
                BuildJsonInvokeRequest(configuredRuntime, configuredRuntime.Invoke.SyncScenario),
                cancellationToken).ConfigureAwait(false);

        return appResult;
    }

    /// <summary>
    /// 使用调用方传入的 base64 图片同步调用 WorkflowAppRuntime，并按 app-result 模式读取结果。
    /// </summary>
    /// <param name="runtimeName">runtime key。</param>
    /// <param name="imageBase64">图片 base64 或 data URL。</param>
    /// <param name="mediaType">可选 media type；data URL 会优先使用自身声明。</param>
    /// <param name="cancellationToken">取消信号。</param>
    /// <returns>app-result 响应。</returns>
    public async Task<WorkflowAppResultResponse> InvokeRuntimeAppResultWithImageBase64Async(
        string runtimeName,
        string imageBase64,
        string? mediaType = null,
        CancellationToken cancellationToken = default)
    {
        var configuredRuntime = GetConfiguredRuntime(runtimeName);
        var workflowRuntimeId = RequireRuntimeId(configuredRuntime);
        var request = BuildImageInvokeRequestFromBase64(
            configuredRuntime,
            imageBase64,
            mediaType,
            configuredRuntime.Invoke.SyncScenario);
        var appResult = await client.InvokeWorkflowAppRuntimeWithImageBase64AppResultResponseAsync(
            workflowRuntimeId,
            request,
            cancellationToken).ConfigureAwait(false);
        return appResult;
    }

    /// <summary>
    /// 使用调用方传入的图片 bytes 同步调用 WorkflowAppRuntime，并按 app-result 模式读取结果。
    /// </summary>
    /// <param name="runtimeName">runtime key。</param>
    /// <param name="imageBytes">图片编码 bytes，通常来自工业相机 SDK 或内存缓存。</param>
    /// <param name="mediaType">media type。</param>
    /// <param name="cancellationToken">取消信号。</param>
    /// <returns>app-result 响应。</returns>
    public async Task<WorkflowAppResultResponse> InvokeRuntimeAppResultWithImageBytesAsync(
        string runtimeName,
        byte[] imageBytes,
        string mediaType = "image/octet-stream",
        CancellationToken cancellationToken = default)
    {
        var configuredRuntime = GetConfiguredRuntime(runtimeName);
        var workflowRuntimeId = RequireRuntimeId(configuredRuntime);
        var request = BuildImageInvokeRequestFromBytes(
            configuredRuntime,
            imageBytes,
            mediaType,
            configuredRuntime.Invoke.SyncScenario);
        var appResult = await client.InvokeWorkflowAppRuntimeWithImageBase64AppResultResponseAsync(
            workflowRuntimeId,
            request,
            cancellationToken).ConfigureAwait(false);
        return appResult;
    }

    /// <summary>
    /// 使用调用方传入的图片文件路径同步调用 WorkflowAppRuntime，并按 app-result 模式读取结果。
    /// </summary>
    /// <param name="runtimeName">runtime key。</param>
    /// <param name="imagePath">图片文件路径。</param>
    /// <param name="mediaType">可选 media type；为空时按扩展名推断。</param>
    /// <param name="cancellationToken">取消信号。</param>
    /// <returns>app-result 响应。</returns>
    public async Task<WorkflowAppResultResponse> InvokeRuntimeAppResultWithImageFromFileAsync(
        string runtimeName,
        string imagePath,
        string? mediaType = null,
        CancellationToken cancellationToken = default)
    {
        var configuredRuntime = GetConfiguredRuntime(runtimeName);
        var workflowRuntimeId = RequireRuntimeId(configuredRuntime);
        var request = BuildImageInvokeRequestFromFile(
            configuredRuntime,
            imagePath,
            mediaType,
            configuredRuntime.Invoke.SyncScenario);
        var appResult = await client.InvokeWorkflowAppRuntimeWithImageBase64AppResultResponseAsync(
            workflowRuntimeId,
            request,
            cancellationToken).ConfigureAwait(false);
        return appResult;
    }
}
}
