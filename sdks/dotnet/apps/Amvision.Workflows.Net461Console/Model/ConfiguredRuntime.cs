namespace Amvision.Workflows.Net461Console.Model;

/// <summary>
/// 已展开后的 runtime 配置项，合并 backend、runtime、invoke 和 cleanup 信息。
/// </summary>
internal sealed class ConfiguredRuntime
{
    /// <summary>
    /// 创建一个可按 runtime key 查询和调用的配置对象。
    /// </summary>
    /// <param name="backend">HTTP API 连接配置。</param>
    /// <param name="runtime">WorkflowAppRuntime 配置。</param>
    /// <param name="invoke">runtime 调用配置。</param>
    /// <param name="cleanup">运行结束后的清理策略。</param>
    /// <param name="sourceFile">来源 config_*.json 文件路径。</param>
    public ConfiguredRuntime(BackendConfig backend, WorkflowRuntimeConfig runtime, InvokeConfig invoke, CleanupConfig cleanup, string sourceFile)
    {
        Backend = backend;
        Runtime = runtime;
        Invoke = invoke;
        Cleanup = cleanup;
        SourceFile = sourceFile;
    }

    /// <summary>
    /// HTTP API 连接配置。
    /// </summary>
    public BackendConfig Backend { get; }

    /// <summary>
    /// WorkflowAppRuntime 配置。
    /// </summary>
    public WorkflowRuntimeConfig Runtime { get; }

    /// <summary>
    /// runtime invoke 和 WorkflowRun 调用配置。
    /// </summary>
    public InvokeConfig Invoke { get; }

    /// <summary>
    /// runtime 调用结束后的清理策略。
    /// </summary>
    public CleanupConfig Cleanup { get; }

    /// <summary>
    /// 当前配置来源文件，用于解析相对路径和定位配置错误。
    /// </summary>
    public string SourceFile { get; }
}
