using System.Threading;
using System.Threading.Tasks;

namespace Amvision.Workflows.Net461Console.TriggerSource;

/// <summary>
/// TriggerSource 创建操作。
/// </summary>
internal sealed partial class WorkflowTriggerSourceOperations
{
    /// <summary>
    /// 按 TriggerSource key 创建后端 TriggerSource。
    /// </summary>
    /// <param name="triggerSourceName">TriggerSource key。</param>
    /// <param name="cancellationToken">取消信号。</param>
    /// <returns>TriggerSource 响应。</returns>
    public async Task<WorkflowTriggerSourceResponse> CreateTriggerSourceAsync(
        string triggerSourceName,
        CancellationToken cancellationToken = default)
    {
        var configuredTriggerSource = GetConfiguredTriggerSource(triggerSourceName);
        var response = await client.CreateTriggerSourceResponseAsync(
            BuildCreateRequest(configuredTriggerSource),
            cancellationToken).ConfigureAwait(false);

        Console.WriteLine($"Created TriggerSource: {configuredTriggerSource.TriggerSource.Name} | {response.TriggerSourceId}");
        return response;
    }
}
