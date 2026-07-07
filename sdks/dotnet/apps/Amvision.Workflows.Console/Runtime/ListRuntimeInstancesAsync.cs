using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;

namespace Amvision.Workflows.Console.Runtime;

/// <summary>
/// WorkflowAppRuntime worker instance 列表读取操作。
/// </summary>
internal sealed partial class WorkflowRuntimeOperations
{
    /// <summary>
    /// 按 runtime key 读取当前 runtime 的 worker instances。
    /// </summary>
    /// <param name="runtimeName">runtime key。</param>
    /// <param name="cancellationToken">取消信号。</param>
    /// <returns>worker instance 列表。</returns>
    public async Task<IReadOnlyList<WorkflowAppRuntimeInstanceResponse>> ListRuntimeInstancesAsync(
        string runtimeName,
        CancellationToken cancellationToken = default)
    {
        var configuredRuntime = GetConfiguredRuntime(runtimeName);
        var instances = await client.ListWorkflowAppRuntimeInstanceResponsesAsync(
            RequireRuntimeId(configuredRuntime),
            cancellationToken).ConfigureAwait(false);

        return instances;
    }
}
