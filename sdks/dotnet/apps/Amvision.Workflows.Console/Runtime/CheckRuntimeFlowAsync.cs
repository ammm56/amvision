using System.Threading;
using System.Threading.Tasks;
using Amvision.Workflows.Console.Model;

namespace Amvision.Workflows.Console.Runtime;

/// <summary>
/// WorkflowAppRuntime 常用调用链检查流程。
/// </summary>
internal sealed partial class WorkflowRuntimeOperations
{
    /// <summary>
    /// 按 runtime key 执行 health、instances、sync invoke、async run 和事件查询，用于快速检查调用链是否可用。
    /// </summary>
    /// <param name="runtimeName">runtime key。</param>
    /// <param name="cancellationToken">取消信号。</param>
    /// <returns>调用链检查结果。</returns>
    public async Task<RuntimeFlowCheckResult> CheckRuntimeFlowAsync(
        string runtimeName,
        CancellationToken cancellationToken = default)
    {
        var runtimeHealth = await GetRuntimeHealthAsync(runtimeName, cancellationToken).ConfigureAwait(false);
        var runtimeInstances = await ListRuntimeInstancesAsync(runtimeName, cancellationToken).ConfigureAwait(false);
        var appResult = await InvokeRuntimeAppResultAsync(runtimeName, cancellationToken).ConfigureAwait(false);

        var run = await RunRuntimeAsync(runtimeName, cancellationToken).ConfigureAwait(false);
        var loadedRun = await GetWorkflowRunAsync(run.WorkflowRunId, cancellationToken).ConfigureAwait(false);
        var runEvents = await GetWorkflowRunEventsAsync(runtimeName, run.WorkflowRunId, cancellationToken).ConfigureAwait(false);
        var runtimeEvents = await GetRuntimeEventsAsync(runtimeName, cancellationToken).ConfigureAwait(false);

        return new RuntimeFlowCheckResult
        {
            RuntimeHealth = runtimeHealth,
            RuntimeInstances = runtimeInstances,
            AppResult = appResult,
            CreatedRun = run,
            LoadedRun = loadedRun,
            RunEvents = runEvents,
            RuntimeEvents = runtimeEvents
        };
    }
}
