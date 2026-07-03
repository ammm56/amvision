using System.Threading;
using System.Threading.Tasks;

namespace Amvision.Workflows.Net461Console.Runtime;

/// <summary>
/// WorkflowAppRuntime 删除操作。
/// </summary>
internal sealed partial class WorkflowRuntimeOperations
{
    /// <summary>
    /// 删除 runtime key 对应的 WorkflowAppRuntime。
    /// </summary>
    /// <param name="runtimeName">runtime key。</param>
    /// <param name="cancellationToken">取消信号。</param>
    public async Task DeleteRuntimeAsync(string runtimeName, CancellationToken cancellationToken = default)
    {
        var configuredRuntime = GetConfiguredRuntime(runtimeName);
        var workflowRuntimeId = RequireRuntimeId(configuredRuntime);
        var response = await client.DeleteWorkflowAppRuntimeAsync(workflowRuntimeId, cancellationToken).ConfigureAwait(false);
        response.EnsureSuccessStatusCode();
        Console.WriteLine($"Deleted runtime: {configuredRuntime.Runtime.Name} | {workflowRuntimeId}");
    }
}
