using System;
using Amvision.Workflows;
using System.Collections.Generic;
using Newtonsoft.Json;

namespace Amvision.Workflows.Configuration
{
/// <summary>
/// 单个 config_*.json 文件的完整配置模型。
/// </summary>
internal sealed class WorkflowAppConfigFile
{
    /// <summary>
    /// 后端 HTTP API 连接配置。
    /// </summary>
    [JsonProperty("backend")]
    public BackendConfig Backend { get; set; } = new BackendConfig();

    /// <summary>
    /// 当前配置文件描述的 WorkflowAppRuntime。
    /// </summary>
    [JsonProperty("runtime")]
    public WorkflowRuntimeConfig? Runtime { get; set; }

    /// <summary>
    /// runtime invoke 和 WorkflowRun 调用参数。
    /// </summary>
    [JsonProperty("invoke")]
    public InvokeConfig? Invoke { get; set; }

    /// <summary>
    /// 与当前 runtime 关联的 TriggerSource 列表。
    /// </summary>
    [JsonProperty("trigger_sources")]
    public List<TriggerSourceConfig> TriggerSources { get; set; } = new List<TriggerSourceConfig>();

    /// <summary>
    /// 当前配置文件中声明的模型 DeploymentInstance 调用列表。
    /// </summary>
    [JsonProperty("model_deployments")]
    public List<ModelDeploymentConfig> ModelDeployments { get; set; } = new List<ModelDeploymentConfig>();

    /// <summary>
    /// 校验整个配置文件，并让子配置能拿到清晰的字段路径。
    /// </summary>
    /// <param name="sourceFile">配置文件名。</param>
    public void Validate(string sourceFile)
    {
        Backend.Validate($"{sourceFile}.backend");
        if (Runtime != null)
        {
            Runtime.Validate($"{sourceFile}.runtime");
            (Invoke ?? new InvokeConfig()).Validate($"{sourceFile}.invoke");
        }
        else if (TriggerSources.Count > 0)
        {
            throw new InvalidOperationException($"{sourceFile}.runtime is required when trigger_sources is not empty.");
        }
        else if (Invoke != null)
        {
            throw new InvalidOperationException($"{sourceFile}.invoke requires runtime.");
        }

        if (Runtime == null && ModelDeployments.Count == 0)
        {
            throw new InvalidOperationException($"{sourceFile} must contain runtime or model_deployments.");
        }

        for (var index = 0; index < TriggerSources.Count; index++)
        {
            TriggerSources[index].Validate($"{sourceFile}.trigger_sources[{index}]");
        }

        for (var index = 0; index < ModelDeployments.Count; index++)
        {
            ModelDeployments[index].Validate($"{sourceFile}.model_deployments[{index}]");
        }
    }
}
}
