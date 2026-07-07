using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;

namespace Amvision.Workflows.Console.TriggerSource;

/// <summary>
/// Project 下 TriggerSource 列表读取操作。
/// </summary>
internal sealed partial class WorkflowTriggerSourceOperations
{
    /// <summary>
    /// 使用 runtime key 对应的 project_id 列出后端 TriggerSource。
    /// </summary>
    /// <param name="runtimeName">runtime key。</param>
    /// <param name="cancellationToken">取消信号。</param>
    /// <returns>TriggerSource 列表。</returns>
    public async Task<IReadOnlyList<WorkflowTriggerSourceResponse>> ListTriggerSourcesAsync(
        string runtimeName,
        CancellationToken cancellationToken = default)
    {
        var configuredRuntime = catalog.GetRuntime(runtimeName);
        var response = await client.ListTriggerSourceResponsesAsync(
            configuredRuntime.Backend.ProjectId,
            limit: 100,
            cancellationToken: cancellationToken).ConfigureAwait(false);

        return response;
    }
}
