using System;
using Amvision.Workflows;
using System.Threading;
using System.Threading.Tasks;

namespace Amvision.Workflows.TriggerSource
{
/// <summary>
/// TriggerSource 停用操作。
/// </summary>
internal sealed partial class WorkflowTriggerSourceOperations
{
    /// <summary>
    /// 按 TriggerSource key 停用后端 TriggerSource。
    /// </summary>
    /// <param name="triggerSourceName">TriggerSource key。</param>
    /// <param name="cancellationToken">取消信号。</param>
    /// <returns>TriggerSource 响应。</returns>
    public async Task<WorkflowTriggerSourceResponse> DisableTriggerSourceAsync(
        string triggerSourceName,
        CancellationToken cancellationToken = default)
    {
        var configuredTriggerSource = GetConfiguredTriggerSource(triggerSourceName);
        var response = await client.DisableTriggerSourceResponseAsync(
            configuredTriggerSource.TriggerSource.TriggerSourceId,
            cancellationToken).ConfigureAwait(false);

        return response;
    }
}
}
