using System.Collections.Generic;
using System.Text.Json.Serialization;

namespace Amvision.Workflows.Console.Model;

/// <summary>
/// 单个 config_*.json 文件的完整配置模型。
/// </summary>
internal sealed class WorkflowAppConfigFile
{
    /// <summary>
    /// 后端 HTTP API 连接配置。
    /// </summary>
    [JsonPropertyName("backend")]
    public BackendConfig Backend { get; set; } = new BackendConfig();

    /// <summary>
    /// 当前配置文件描述的 WorkflowAppRuntime。
    /// </summary>
    [JsonPropertyName("runtime")]
    public WorkflowRuntimeConfig Runtime { get; set; } = new WorkflowRuntimeConfig();

    /// <summary>
    /// runtime invoke 和 WorkflowRun 调用参数。
    /// </summary>
    [JsonPropertyName("invoke")]
    public InvokeConfig Invoke { get; set; } = new InvokeConfig();

    /// <summary>
    /// 与当前 runtime 关联的 TriggerSource 列表。
    /// </summary>
    [JsonPropertyName("trigger_sources")]
    public List<TriggerSourceConfig> TriggerSources { get; set; } = new List<TriggerSourceConfig>();

    /// <summary>
    /// 校验整个配置文件，并让子配置能拿到清晰的字段路径。
    /// </summary>
    /// <param name="sourceFile">配置文件名。</param>
    public void Validate(string sourceFile)
    {
        Backend.Validate($"{sourceFile}.backend");
        Runtime.Validate($"{sourceFile}.runtime");
        Invoke.Validate($"{sourceFile}.invoke");
        for (var index = 0; index < TriggerSources.Count; index++)
        {
            TriggerSources[index].Validate($"{sourceFile}.trigger_sources[{index}]");
        }
    }
}
