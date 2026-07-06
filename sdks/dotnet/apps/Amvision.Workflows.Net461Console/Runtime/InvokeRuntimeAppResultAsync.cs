using System.Threading;
using System.Threading.Tasks;

namespace Amvision.Workflows.Net461Console.Runtime;

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
}
