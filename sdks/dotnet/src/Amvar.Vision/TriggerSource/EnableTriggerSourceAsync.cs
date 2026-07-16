using System;
using Amvar.Vision;
using System.Threading;
using System.Threading.Tasks;

namespace Amvar.Vision.TriggerSource
{
/// <summary>
/// TriggerSource 启用操作。
/// </summary>
internal sealed partial class WorkflowTriggerSourceOperations
{
    /// <summary>
    /// 按 TriggerSource key 启用后端 TriggerSource。
    /// </summary>
    /// <param name="triggerSourceName">TriggerSource key。</param>
    /// <param name="cancellationToken">取消信号。</param>
    /// <returns>TriggerSource 响应。</returns>
    public async Task<WorkflowTriggerSourceResponse> EnableTriggerSourceAsync(
        string triggerSourceName,
        CancellationToken cancellationToken = default)
    {
        var configuredTriggerSource = GetConfiguredTriggerSource(triggerSourceName);
        var response = await client.EnableTriggerSourceResponseAsync(
            configuredTriggerSource.TriggerSource.TriggerSourceId,
            cancellationToken).ConfigureAwait(false);

        return response;
    }
}
}
