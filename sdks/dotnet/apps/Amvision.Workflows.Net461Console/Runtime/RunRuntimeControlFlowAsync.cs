using System.Threading;
using System.Threading.Tasks;

namespace Amvision.Workflows.Net461Console.Runtime;

/// <summary>
/// WorkflowAppRuntime 端到端控制流程。
/// </summary>
internal sealed partial class WorkflowRuntimeOperations
{
    /// <summary>
    /// 按 runtime key 执行 list、resolve、start、health、invoke、run、events 和可选 cleanup。
    /// </summary>
    /// <param name="runtimeName">runtime key。</param>
    /// <param name="cancellationToken">取消信号。</param>
    public async Task RunRuntimeControlFlowAsync(string runtimeName, CancellationToken cancellationToken = default)
    {
        await ListProjectRuntimesAsync(runtimeName, cancellationToken).ConfigureAwait(false);
        await ResolveRuntimeAsync(runtimeName, cancellationToken).ConfigureAwait(false);
        await StartRuntimeAsync(runtimeName, cancellationToken).ConfigureAwait(false);
        await GetRuntimeHealthAsync(runtimeName, cancellationToken).ConfigureAwait(false);
        await ListRuntimeInstancesAsync(runtimeName, cancellationToken).ConfigureAwait(false);
        await InvokeRuntimeAppResultAsync(runtimeName, cancellationToken).ConfigureAwait(false);

        var run = await CreateWorkflowRunAsync(runtimeName, cancellationToken).ConfigureAwait(false);
        await GetWorkflowRunAsync(run.WorkflowRunId, cancellationToken).ConfigureAwait(false);
        await GetWorkflowRunEventsAsync(runtimeName, run.WorkflowRunId, cancellationToken).ConfigureAwait(false);
        await GetRuntimeEventsAsync(runtimeName, cancellationToken).ConfigureAwait(false);

        if (GetConfiguredRuntime(runtimeName).Runtime.RestartRuntime)
        {
            await RestartRuntimeAsync(runtimeName, cancellationToken).ConfigureAwait(false);
            await GetRuntimeHealthAsync(runtimeName, cancellationToken).ConfigureAwait(false);
        }

        await CleanupRuntimeAsync(runtimeName, cancellationToken).ConfigureAwait(false);
    }
}
