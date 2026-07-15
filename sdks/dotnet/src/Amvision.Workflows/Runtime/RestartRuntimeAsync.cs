using System;
using Amvision.Workflows;
using System.Threading;
using System.Threading.Tasks;

namespace Amvision.Workflows.Runtime
{
/// <summary>
/// WorkflowAppRuntime 重启操作。
/// </summary>
internal sealed partial class WorkflowRuntimeOperations
{
    /// <summary>
    /// 按 runtime key 重启 WorkflowAppRuntime。
    /// </summary>
    /// <param name="runtimeName">runtime key。</param>
    /// <param name="cancellationToken">取消信号。</param>
    /// <returns>重启后的 runtime 响应。</returns>
    public async Task<WorkflowAppRuntimeResponse> RestartRuntimeAsync(
        string runtimeName,
        CancellationToken cancellationToken = default)
    {
        var configuredRuntime = GetConfiguredRuntime(runtimeName);
        var runtime = await client.RestartWorkflowAppRuntimeResponseAsync(
            RequireRuntimeId(configuredRuntime),
            cancellationToken).ConfigureAwait(false);

        return runtime;
    }
}
}
