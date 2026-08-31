using System;
using System.Collections.Generic;
using Amvar.Vision;
using Newtonsoft.Json;

namespace Amvar.Vision.Configuration
{
/// <summary>
/// WorkflowAppRuntime 调用链检查结果，调用方可直接绑定到界面或用于业务判断。
/// </summary>
public sealed class RuntimeFlowCheckResult
{
    /// <summary>
    /// runtime health 查询结果。
    /// </summary>
    [JsonProperty("runtime_health")]
    public WorkflowAppRuntimeResponse RuntimeHealth { get; set; } = new WorkflowAppRuntimeResponse();

    /// <summary>
    /// runtime worker instance 列表。
    /// </summary>
    [JsonProperty("runtime_instances")]
    public IReadOnlyList<WorkflowAppRuntimeInstanceResponse> RuntimeInstances { get; set; } =
        new List<WorkflowAppRuntimeInstanceResponse>();

    /// <summary>
    /// sync invoke 的 app-result 响应。
    /// </summary>
    [JsonProperty("app_result")]
    public WorkflowAppResultResponse AppResult { get; set; } = null!;

    /// <summary>
    /// async run 创建后的 WorkflowRun 响应。
    /// </summary>
    [JsonProperty("created_run")]
    public WorkflowRunResponse CreatedRun { get; set; } = new WorkflowRunResponse();

    /// <summary>
    /// 按 workflow_run_id 重新读取到的 WorkflowRun 响应。
    /// </summary>
    [JsonProperty("loaded_run")]
    public WorkflowRunResponse LoadedRun { get; set; } = new WorkflowRunResponse();

    /// <summary>
    /// WorkflowRun 事件列表。
    /// </summary>
    [JsonProperty("run_events")]
    public IReadOnlyList<WorkflowRunEventResponse> RunEvents { get; set; } =
        new List<WorkflowRunEventResponse>();

    /// <summary>
    /// runtime 事件列表。
    /// </summary>
    [JsonProperty("runtime_events")]
    public IReadOnlyList<WorkflowAppRuntimeEventResponse> RuntimeEvents { get; set; } =
        new List<WorkflowAppRuntimeEventResponse>();
}
}
