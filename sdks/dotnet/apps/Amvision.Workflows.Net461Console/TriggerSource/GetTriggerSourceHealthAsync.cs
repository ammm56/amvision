using System.Threading;
using System.Threading.Tasks;

namespace Amvision.Workflows.Net461Console.TriggerSource;

/// <summary>
/// TriggerSource health 查询操作。
/// </summary>
internal sealed partial class WorkflowTriggerSourceOperations
{
    /// <summary>
    /// 按 TriggerSource key 查询后端 adapter health。
    /// </summary>
    /// <param name="triggerSourceName">TriggerSource key。</param>
    /// <param name="cancellationToken">取消信号。</param>
    /// <returns>TriggerSource health 响应。</returns>
    public async Task<WorkflowTriggerSourceHealthResponse> GetTriggerSourceHealthAsync(
        string triggerSourceName,
        CancellationToken cancellationToken = default)
    {
        var configuredTriggerSource = GetConfiguredTriggerSource(triggerSourceName);
        var response = await client.GetTriggerSourceHealthResponseAsync(
            configuredTriggerSource.TriggerSource.TriggerSourceId,
            cancellationToken).ConfigureAwait(false);

        return response;
    }
}
