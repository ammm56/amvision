using System;
using Amvision.Workflows;
namespace Amvision.Workflows.Console.Model
{
/// <summary>
/// 已展开后的 TriggerSource 配置项，绑定对应 backend、runtime 和 TriggerSource。
/// </summary>
internal sealed class ConfiguredTriggerSource
{
    /// <summary>
    /// 构造一个可按 TriggerSource key 查询和调用的配置对象。
    /// </summary>
    /// <param name="backend">HTTP API 连接配置。</param>
    /// <param name="runtime">TriggerSource 关联的 WorkflowAppRuntime 配置。</param>
    /// <param name="triggerSource">TriggerSource 配置。</param>
    /// <param name="sourceFile">来源 config_*.json 文件路径。</param>
    public ConfiguredTriggerSource(BackendConfig backend, WorkflowRuntimeConfig runtime, TriggerSourceConfig triggerSource, string sourceFile)
    {
        Backend = backend;
        Runtime = runtime;
        TriggerSource = triggerSource;
        SourceFile = sourceFile;
    }

    /// <summary>
    /// HTTP API 连接配置。
    /// </summary>
    public BackendConfig Backend { get; }

    /// <summary>
    /// TriggerSource 关联的 WorkflowAppRuntime 配置。
    /// </summary>
    public WorkflowRuntimeConfig Runtime { get; }

    /// <summary>
    /// TriggerSource 控制和协议调用配置。
    /// </summary>
    public TriggerSourceConfig TriggerSource { get; }

    /// <summary>
    /// 当前配置来源文件，用于解析相对路径和定位配置错误。
    /// </summary>
    public string SourceFile { get; }
}
}
