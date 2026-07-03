using System.Threading;
using System.Threading.Tasks;

namespace Amvision.Workflows.Net461Console.TriggerSource;

/// <summary>
/// TriggerSource 读取操作。
/// </summary>
internal sealed partial class WorkflowTriggerSourceOperations
{
    /// <summary>
    /// 按 TriggerSource key 读取后端 TriggerSource 记录。
    /// </summary>
    /// <param name="triggerSourceName">TriggerSource key。</param>
    /// <param name="cancellationToken">取消信号。</param>
    /// <returns>TriggerSource 响应。</returns>
    public async Task<WorkflowTriggerSourceResponse> GetTriggerSourceAsync(
        string triggerSourceName,
        CancellationToken cancellationToken = default)
    {
        var configuredTriggerSource = GetConfiguredTriggerSource(triggerSourceName);
        var response = await client.GetTriggerSourceResponseAsync(
            configuredTriggerSource.TriggerSource.TriggerSourceId,
            cancellationToken).ConfigureAwait(false);

        Console.WriteLine($"Loaded TriggerSource: {configuredTriggerSource.TriggerSource.Name} | {response.DesiredState}/{response.ObservedState}");
        return response;
    }
}
