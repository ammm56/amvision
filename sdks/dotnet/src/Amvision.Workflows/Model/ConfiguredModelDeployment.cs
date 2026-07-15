using System;
using Amvision.Workflows;
namespace Amvision.Workflows.Configuration
{
/// <summary>
/// 已展开后的模型部署配置项，绑定 backend 和 DeploymentInstance 调用参数。
/// </summary>
internal sealed class ConfiguredModelDeployment
{
    /// <summary>
    /// 构造一个可按模型部署 key 查询和调用的配置对象。
    /// </summary>
    /// <param name="backend">HTTP API 连接配置。</param>
    /// <param name="modelDeployment">模型 DeploymentInstance 调用配置。</param>
    /// <param name="sourceFile">来源 config_*.json 文件路径。</param>
    public ConfiguredModelDeployment(BackendConfig backend, ModelDeploymentConfig modelDeployment, string sourceFile)
    {
        Backend = backend;
        ModelDeployment = modelDeployment;
        SourceFile = sourceFile;
    }

    /// <summary>
    /// HTTP API 连接配置。
    /// </summary>
    public BackendConfig Backend { get; }

    /// <summary>
    /// 模型 DeploymentInstance 调用配置。
    /// </summary>
    public ModelDeploymentConfig ModelDeployment { get; }

    /// <summary>
    /// 当前配置来源文件，用于解析相对路径和定位配置错误。
    /// </summary>
    public string SourceFile { get; }
}
}
