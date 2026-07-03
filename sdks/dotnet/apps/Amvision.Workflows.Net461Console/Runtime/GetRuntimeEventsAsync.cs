using System.Linq;
using System.Threading;
using System.Threading.Tasks;

namespace Amvision.Workflows.Net461Console.Runtime;

/// <summary>
/// WorkflowAppRuntime 事件读取操作。
/// </summary>
internal sealed partial class WorkflowRuntimeOperations
{
    /// <summary>
    /// 按 runtime key 读取 runtime 事件，并按配置输出预览。
    /// </summary>
    /// <param name="runtimeName">runtime key。</param>
    /// <param name="cancellationToken">取消信号。</param>
    public async Task GetRuntimeEventsAsync(string runtimeName, CancellationToken cancellationToken = default)
    {
        var configuredRuntime = GetConfiguredRuntime(runtimeName);
        var events = await client.GetWorkflowAppRuntimeEventResponsesAsync(
            RequireRuntimeId(configuredRuntime),
            limit: configuredRuntime.Invoke.EventLimit,
            cancellationToken: cancellationToken).ConfigureAwait(false);

        Console.WriteLine($"Runtime events: {events.Count}");
        foreach (var item in events.Take(configuredRuntime.Invoke.EventPreviewCount))
        {
            Console.WriteLine($"  #{item.Sequence} {item.EventType}");
        }
    }
}
