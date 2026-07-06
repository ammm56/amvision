using System.Threading;
using System.Threading.Tasks;

namespace Amvision.Workflows.Net461Console.Runtime;

/// <summary>
/// WorkflowRun 读取操作。
/// </summary>
internal sealed partial class WorkflowRuntimeOperations
{
    /// <summary>
    /// 按 workflow_run_id 读取 WorkflowRun。
    /// </summary>
    /// <param name="workflowRunId">WorkflowRun id。</param>
    /// <param name="cancellationToken">取消信号。</param>
    /// <returns>WorkflowRun 响应。</returns>
    public async Task<WorkflowRunResponse> GetWorkflowRunAsync(
        string workflowRunId,
        CancellationToken cancellationToken = default)
    {
        var run = await client.GetWorkflowRunResponseAsync(
            workflowRunId,
            WorkflowResponseModes.Run,
            cancellationToken).ConfigureAwait(false);

        return run;
    }
}
