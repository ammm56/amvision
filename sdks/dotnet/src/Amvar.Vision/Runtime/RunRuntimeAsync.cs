using System;
using Amvar.Vision;
using System.Threading;
using System.Threading.Tasks;

namespace Amvar.Vision.Runtime
{
/// <summary>
/// WorkflowAppRuntime 异步 run 调用。
/// </summary>
internal sealed partial class WorkflowRuntimeOperations
{
    /// <summary>
    /// 使用 runtime key 发起一次异步 run，后端会创建一条 WorkflowRun 运行记录。
    /// </summary>
    /// <param name="runtimeName">runtime key。</param>
    /// <param name="cancellationToken">取消信号。</param>
    /// <returns>WorkflowRun 响应。</returns>
    public async Task<WorkflowRunResponse> RunRuntimeAsync(
        string runtimeName,
        CancellationToken cancellationToken = default)
    {
        var configuredRuntime = GetConfiguredRuntime(runtimeName);
        var run = await client.CreateWorkflowRunResponseAsync(
            RequireRuntimeId(configuredRuntime),
            BuildWorkflowRunRequest(configuredRuntime, configuredRuntime.Invoke.AsyncScenario),
            cancellationToken).ConfigureAwait(false);

        return run;
    }

    /// <summary>
    /// 使用调用方传入的 base64 图片发起异步 WorkflowRun。
    /// </summary>
    /// <param name="runtimeName">runtime key。</param>
    /// <param name="imageBase64">图片 base64 或 data URL。</param>
    /// <param name="mediaType">可选 media type；data URL 会优先使用自身声明。</param>
    /// <param name="cancellationToken">取消信号。</param>
    /// <returns>WorkflowRun 响应。</returns>
    public async Task<WorkflowRunResponse> RunRuntimeWithImageBase64Async(
        string runtimeName,
        string imageBase64,
        string? mediaType = null,
        CancellationToken cancellationToken = default)
    {
        var configuredRuntime = GetConfiguredRuntime(runtimeName);
        var run = await client.CreateWorkflowRunWithImageBase64ResponseAsync(
            RequireRuntimeId(configuredRuntime),
            BuildImageInvokeRequestFromBase64(
                configuredRuntime,
                imageBase64,
                mediaType,
                configuredRuntime.Invoke.AsyncScenario),
            cancellationToken).ConfigureAwait(false);

        return run;
    }

    /// <summary>
    /// 使用调用方传入的图片 bytes 发起异步 WorkflowRun。
    /// </summary>
    /// <param name="runtimeName">runtime key。</param>
    /// <param name="imageBytes">图片编码 bytes，通常来自工业相机 SDK 或内存缓存。</param>
    /// <param name="mediaType">media type。</param>
    /// <param name="cancellationToken">取消信号。</param>
    /// <returns>WorkflowRun 响应。</returns>
    public async Task<WorkflowRunResponse> RunRuntimeWithImageBytesAsync(
        string runtimeName,
        byte[] imageBytes,
        string mediaType = "image/octet-stream",
        CancellationToken cancellationToken = default)
    {
        var configuredRuntime = GetConfiguredRuntime(runtimeName);
        var run = await client.CreateWorkflowRunWithImageBase64ResponseAsync(
            RequireRuntimeId(configuredRuntime),
            BuildImageInvokeRequestFromBytes(
                configuredRuntime,
                imageBytes,
                mediaType,
                configuredRuntime.Invoke.AsyncScenario),
            cancellationToken).ConfigureAwait(false);

        return run;
    }

    /// <summary>
    /// 使用调用方传入的图片文件路径发起异步 WorkflowRun。
    /// </summary>
    /// <param name="runtimeName">runtime key。</param>
    /// <param name="imagePath">图片文件路径。</param>
    /// <param name="mediaType">可选 media type；为空时按扩展名推断。</param>
    /// <param name="cancellationToken">取消信号。</param>
    /// <returns>WorkflowRun 响应。</returns>
    public async Task<WorkflowRunResponse> RunRuntimeWithImageFromFileAsync(
        string runtimeName,
        string imagePath,
        string? mediaType = null,
        CancellationToken cancellationToken = default)
    {
        var configuredRuntime = GetConfiguredRuntime(runtimeName);
        var run = await client.CreateWorkflowRunWithImageBase64ResponseAsync(
            RequireRuntimeId(configuredRuntime),
            BuildImageInvokeRequestFromFile(
                configuredRuntime,
                imagePath,
                mediaType,
                configuredRuntime.Invoke.AsyncScenario),
            cancellationToken).ConfigureAwait(false);

        return run;
    }
}
}
