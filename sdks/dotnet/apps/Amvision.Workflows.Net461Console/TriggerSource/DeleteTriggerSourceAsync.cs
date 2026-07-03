using System.Threading;
using System.Threading.Tasks;

namespace Amvision.Workflows.Net461Console.TriggerSource;

/// <summary>
/// TriggerSource 删除操作。
/// </summary>
internal sealed partial class WorkflowTriggerSourceOperations
{
    /// <summary>
    /// 按 TriggerSource key 删除后端 TriggerSource。
    /// </summary>
    /// <param name="triggerSourceName">TriggerSource key。</param>
    /// <param name="cancellationToken">取消信号。</param>
    public async Task DeleteTriggerSourceAsync(
        string triggerSourceName,
        CancellationToken cancellationToken = default)
    {
        var configuredTriggerSource = GetConfiguredTriggerSource(triggerSourceName);
        var response = await client.DeleteTriggerSourceAsync(
            configuredTriggerSource.TriggerSource.TriggerSourceId,
            cancellationToken).ConfigureAwait(false);
        response.EnsureSuccessStatusCode();
        Console.WriteLine($"Deleted TriggerSource: {configuredTriggerSource.TriggerSource.Name}");
    }
}
