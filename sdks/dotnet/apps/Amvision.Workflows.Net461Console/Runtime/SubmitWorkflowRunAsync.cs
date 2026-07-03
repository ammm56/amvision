using System.Threading;
using System.Threading.Tasks;

namespace Amvision.Workflows.Net461Console.Runtime;

/// <summary>
/// 异步 WorkflowRun 提交操作。
/// </summary>
internal sealed partial class WorkflowRuntimeOperations
{
    /// <summary>
    /// 使用 runtime key 提交一次异步 WorkflowRun 调用。
    /// </summary>
    /// <param name="runtimeName">runtime key。</param>
    /// <param name="cancellationToken">取消信号。</param>
    /// <returns>WorkflowRun 响应。</returns>
    public async Task<WorkflowRunResponse> SubmitWorkflowRunAsync(
        string runtimeName,
        CancellationToken cancellationToken = default)
    {
        var configuredRuntime = GetConfiguredRuntime(runtimeName);
        var run = await client.CreateWorkflowRunResponseAsync(
            RequireRuntimeId(configuredRuntime),
            BuildWorkflowRunRequest(configuredRuntime, configuredRuntime.Invoke.AsyncScenario),
            cancellationToken).ConfigureAwait(false);

        Console.WriteLine($"Submitted WorkflowRun: {run.WorkflowRunId} | {run.State}");
        return run;
    }
}
