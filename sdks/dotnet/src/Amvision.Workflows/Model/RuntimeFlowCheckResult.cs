using System;
using System.Collections.Generic;
using Amvision.Workflows;

namespace Amvision.Workflows.Configuration
{
/// <summary>
/// WorkflowAppRuntime 调用链检查结果，调用方可直接绑定到界面或用于业务判断。
/// </summary>
public sealed class RuntimeFlowCheckResult
{
    /// <summary>
    /// runtime health 查询结果。
    /// </summary>
    public WorkflowAppRuntimeResponse RuntimeHealth { get; set; } = new WorkflowAppRuntimeResponse();

    /// <summary>
    /// runtime worker instance 列表。
    /// </summary>
    public IReadOnlyList<WorkflowAppRuntimeInstanceResponse> RuntimeInstances { get; set; } =
        new List<WorkflowAppRuntimeInstanceResponse>();

    /// <summary>
    /// sync invoke 的 app-result 响应。
    /// </summary>
    public WorkflowAppResultResponse AppResult { get; set; } = null!;

    /// <summary>
    /// async run 创建后的 WorkflowRun 响应。
    /// </summary>
    public WorkflowRunResponse CreatedRun { get; set; } = new WorkflowRunResponse();

    /// <summary>
    /// 按 workflow_run_id 重新读取到的 WorkflowRun 响应。
    /// </summary>
    public WorkflowRunResponse LoadedRun { get; set; } = new WorkflowRunResponse();

    /// <summary>
    /// WorkflowRun 事件列表。
    /// </summary>
    public IReadOnlyList<WorkflowRunEventResponse> RunEvents { get; set; } =
        new List<WorkflowRunEventResponse>();

    /// <summary>
    /// runtime 事件列表。
    /// </summary>
    public IReadOnlyList<WorkflowAppRuntimeEventResponse> RuntimeEvents { get; set; } =
        new List<WorkflowAppRuntimeEventResponse>();
}
}
