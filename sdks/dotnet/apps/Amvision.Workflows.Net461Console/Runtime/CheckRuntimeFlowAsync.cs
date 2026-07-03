using System.Threading;
using System.Threading.Tasks;

namespace Amvision.Workflows.Net461Console.Runtime;

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
    public async Task CheckRuntimeFlowAsync(string runtimeName, CancellationToken cancellationToken = default)
    {
        await GetRuntimeHealthAsync(runtimeName, cancellationToken).ConfigureAwait(false);
        await ListRuntimeInstancesAsync(runtimeName, cancellationToken).ConfigureAwait(false);
        await InvokeRuntimeAppResultAsync(runtimeName, cancellationToken).ConfigureAwait(false);

        var run = await RunRuntimeAsync(runtimeName, cancellationToken).ConfigureAwait(false);
        await GetWorkflowRunAsync(run.WorkflowRunId, cancellationToken).ConfigureAwait(false);
        await GetWorkflowRunEventsAsync(runtimeName, run.WorkflowRunId, cancellationToken).ConfigureAwait(false);
        await GetRuntimeEventsAsync(runtimeName, cancellationToken).ConfigureAwait(false);
    }
}
