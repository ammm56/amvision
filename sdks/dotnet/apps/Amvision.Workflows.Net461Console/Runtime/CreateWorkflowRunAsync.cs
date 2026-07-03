using System.Threading;
using System.Threading.Tasks;

namespace Amvision.Workflows.Net461Console.Runtime;

/// <summary>
/// 异步 WorkflowRun 创建操作。
/// </summary>
internal sealed partial class WorkflowRuntimeOperations
{
    /// <summary>
    /// 使用 runtime key 创建异步 WorkflowRun。
    /// </summary>
    /// <param name="runtimeName">runtime key。</param>
    /// <param name="cancellationToken">取消信号。</param>
    /// <returns>WorkflowRun 响应。</returns>
    public async Task<WorkflowRunResponse> CreateWorkflowRunAsync(
        string runtimeName,
        CancellationToken cancellationToken = default)
    {
        var configuredRuntime = GetConfiguredRuntime(runtimeName);
        var run = await client.CreateWorkflowRunResponseAsync(
            RequireRuntimeId(configuredRuntime),
            BuildWorkflowRunRequest(configuredRuntime, configuredRuntime.Invoke.AsyncScenario),
            cancellationToken).ConfigureAwait(false);

        Console.WriteLine($"Created WorkflowRun: {run.WorkflowRunId} | {run.State}");
        return run;
    }
}
