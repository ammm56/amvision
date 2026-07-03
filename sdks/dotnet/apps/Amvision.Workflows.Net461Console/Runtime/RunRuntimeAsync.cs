using System.Threading;
using System.Threading.Tasks;

namespace Amvision.Workflows.Net461Console.Runtime;

/// <summary>
/// WorkflowAppRuntime 异步 run 调用。
/// </summary>
internal sealed partial class WorkflowRuntimeOperations
{
    /// <summary>
    /// 使用 runtime key 发起一次异步 run，后端会创建一条 WorkflowRun 运行记录。
    /// </summary>
    /// <param name="runtimeName">runtime key。</param>
    /// <param name="cancellationToken">取消信号。</param>
    /// <returns>WorkflowRun 响应。</returns>
    public async Task<WorkflowRunResponse> RunRuntimeAsync(
        string runtimeName,
        CancellationToken cancellationToken = default)
    {
        var configuredRuntime = GetConfiguredRuntime(runtimeName);
        var run = await client.CreateWorkflowRunResponseAsync(
            RequireRuntimeId(configuredRuntime),
            BuildWorkflowRunRequest(configuredRuntime, configuredRuntime.Invoke.AsyncScenario),
            cancellationToken).ConfigureAwait(false);

        Console.WriteLine($"Runtime run created WorkflowRun: {run.WorkflowRunId} | {run.State}");
        return run;
    }
}
