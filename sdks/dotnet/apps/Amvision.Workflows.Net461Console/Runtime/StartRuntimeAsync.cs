using System.Threading;
using System.Threading.Tasks;

namespace Amvision.Workflows.Net461Console.Runtime;

/// <summary>
/// WorkflowAppRuntime 启动操作。
/// </summary>
internal sealed partial class WorkflowRuntimeOperations
{
    /// <summary>
    /// 按 runtime key 启动 WorkflowAppRuntime。
    /// </summary>
    /// <param name="runtimeName">runtime key。</param>
    /// <param name="cancellationToken">取消信号。</param>
    /// <returns>启动后的 runtime 响应。</returns>
    public async Task<WorkflowAppRuntimeResponse> StartRuntimeAsync(
        string runtimeName,
        CancellationToken cancellationToken = default)
    {
        var configuredRuntime = GetConfiguredRuntime(runtimeName);
        var runtime = await client.StartWorkflowAppRuntimeResponseAsync(
            RequireRuntimeId(configuredRuntime),
            cancellationToken).ConfigureAwait(false);

        Console.WriteLine($"Started runtime: {configuredRuntime.Runtime.Name} | {runtime.WorkflowRuntimeId} | {runtime.DesiredState}/{runtime.ObservedState}");
        return runtime;
    }
}
