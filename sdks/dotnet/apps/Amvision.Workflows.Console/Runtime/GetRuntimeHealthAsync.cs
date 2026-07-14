using System;
using Amvision.Workflows;
using System.Threading;
using System.Threading.Tasks;

namespace Amvision.Workflows.Console.Runtime
{
/// <summary>
/// WorkflowAppRuntime health 查询操作。
/// </summary>
internal sealed partial class WorkflowRuntimeOperations
{
    /// <summary>
    /// 按 runtime key 查询 health。
    /// </summary>
    /// <param name="runtimeName">runtime key。</param>
    /// <param name="cancellationToken">取消信号。</param>
    /// <returns>包含 health summary 的 runtime 响应。</returns>
    public async Task<WorkflowAppRuntimeResponse> GetRuntimeHealthAsync(
        string runtimeName,
        CancellationToken cancellationToken = default)
    {
        var configuredRuntime = GetConfiguredRuntime(runtimeName);
        var runtime = await client.GetWorkflowAppRuntimeHealthResponseAsync(
            RequireRuntimeId(configuredRuntime),
            cancellationToken).ConfigureAwait(false);

        return runtime;
    }
}
}
