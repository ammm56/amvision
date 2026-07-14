using System;
using Amvision.Workflows;
using System.Threading;
using System.Threading.Tasks;

namespace Amvision.Workflows.Console.Runtime
{
/// <summary>
/// WorkflowAppRuntime 停止操作。
/// </summary>
internal sealed partial class WorkflowRuntimeOperations
{
    /// <summary>
    /// 按 runtime key 停止 WorkflowAppRuntime。
    /// </summary>
    /// <param name="runtimeName">runtime key。</param>
    /// <param name="cancellationToken">取消信号。</param>
    /// <returns>停止后的 runtime 响应。</returns>
    public async Task<WorkflowAppRuntimeResponse> StopRuntimeAsync(
        string runtimeName,
        CancellationToken cancellationToken = default)
    {
        var configuredRuntime = GetConfiguredRuntime(runtimeName);
        var runtime = await client.StopWorkflowAppRuntimeResponseAsync(
            RequireRuntimeId(configuredRuntime),
            cancellationToken).ConfigureAwait(false);

        return runtime;
    }
}
}
