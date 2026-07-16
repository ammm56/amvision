using System;
using Amvar.Vision;
using System.Threading;
using System.Threading.Tasks;

namespace Amvar.Vision.Runtime
{
/// <summary>
/// WorkflowRun 取消操作。
/// </summary>
internal sealed partial class WorkflowRuntimeOperations
{
    /// <summary>
    /// 取消一条异步 WorkflowRun。
    /// </summary>
    /// <param name="workflowRunId">WorkflowRun id。</param>
    /// <param name="cancellationToken">取消信号。</param>
    /// <returns>WorkflowRun 响应。</returns>
    public async Task<WorkflowRunResponse> CancelWorkflowRunAsync(
        string workflowRunId,
        CancellationToken cancellationToken = default)
    {
        var run = await client.CancelWorkflowRunResponseAsync(
            workflowRunId,
            cancellationToken).ConfigureAwait(false);

        return run;
    }
}
}
