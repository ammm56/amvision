using System;
using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;
using Amvision.Workflows;

namespace Amvision.Workflows.Runtime
{
/// <summary>
/// WorkflowAppRuntime 事件读取操作。
/// </summary>
internal sealed partial class WorkflowRuntimeOperations
{
    /// <summary>
    /// 按 runtime key 读取 runtime 事件。
    /// </summary>
    /// <param name="runtimeName">runtime key。</param>
    /// <param name="cancellationToken">取消信号。</param>
    /// <returns>runtime 事件列表。</returns>
    public async Task<IReadOnlyList<WorkflowAppRuntimeEventResponse>> GetRuntimeEventsAsync(
        string runtimeName,
        CancellationToken cancellationToken = default)
    {
        var configuredRuntime = GetConfiguredRuntime(runtimeName);
        return await client.GetWorkflowAppRuntimeEventResponsesAsync(
            RequireRuntimeId(configuredRuntime),
            limit: configuredRuntime.Invoke.EventLimit,
            cancellationToken: cancellationToken).ConfigureAwait(false);
    }
}
}
