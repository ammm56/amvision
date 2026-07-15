using System;
using Amvision.Workflows;
using System.IO;
using Amvision.Workflows.Configuration;
using Amvision.Workflows.Tools;

namespace Amvision.Workflows.ModelDeployment
{
/// <summary>
/// 模型 DeploymentInstance 控制和推理调用操作集合。
/// </summary>
internal sealed partial class ModelDeploymentOperations
{
    /// <summary>
    /// 复用的 HTTP SDK client。
    /// </summary>
    private readonly AmvisionWorkflowClient client;

    /// <summary>
    /// runtime、TriggerSource 和模型 deployment 配置索引。
    /// </summary>
    private readonly WorkflowConfigurationCatalog catalog;

    /// <summary>
    /// 初始化模型 deployment 操作对象。
    /// </summary>
    /// <param name="client">HTTP SDK client。</param>
    /// <param name="catalog">配置 catalog。</param>
    public ModelDeploymentOperations(AmvisionWorkflowClient client, WorkflowConfigurationCatalog catalog)
    {
        this.client = client ?? throw new ArgumentNullException(nameof(client));
        this.catalog = catalog ?? throw new ArgumentNullException(nameof(catalog));
    }

    /// <summary>
    /// 按模型 deployment key 获取配置。
    /// </summary>
    /// <param name="modelDeploymentName">模型 deployment key。</param>
    /// <returns>模型 deployment 配置。</returns>
    private ConfiguredModelDeployment GetConfiguredModelDeployment(string modelDeploymentName)
    {
        return catalog.GetModelDeployment(modelDeploymentName);
    }

    /// <summary>
    /// 获取后端 DeploymentInstance id；为空说明前端配置未同步到 config_*.json。
    /// </summary>
    /// <param name="configuredModelDeployment">模型 deployment 配置。</param>
    /// <returns>deployment_instance_id。</returns>
    private static string RequireDeploymentInstanceId(ConfiguredModelDeployment configuredModelDeployment)
    {
        return ConfigValidation.RequireText(
            configuredModelDeployment.ModelDeployment.DeploymentInstanceId,
            $"{configuredModelDeployment.ModelDeployment.Name}.deployment_instance_id");
    }

    /// <summary>
    /// 将配置文件中的相对路径解析为绝对路径。
    /// </summary>
    /// <param name="configuredModelDeployment">模型 deployment 配置。</param>
    /// <param name="configuredPath">配置中的路径。</param>
    /// <returns>绝对路径。</returns>
    private static string ResolveConfiguredPath(ConfiguredModelDeployment configuredModelDeployment, string configuredPath)
    {
        return ConfiguredPathResolver.ResolveExistingFile(
            configuredPath,
            configuredModelDeployment.SourceFile,
            "Model deployment input image file does not exist.");
    }

    /// <summary>
    /// 按图片扩展名推断 HTTP multipart 上传使用的 media type。
    /// </summary>
    /// <param name="imagePath">图片路径。</param>
    /// <returns>MIME media type。</returns>
    private static string InferImageMediaType(string imagePath)
    {
        var extension = Path.GetExtension(imagePath).ToLowerInvariant();
        switch (extension)
        {
            case ".jpg":
            case ".jpeg":
                return "image/jpeg";
            case ".png":
                return "image/png";
            case ".bmp":
                return "image/bmp";
            case ".webp":
                return "image/webp";
            case ".tif":
            case ".tiff":
                return "image/tiff";
            default:
                return "image/octet-stream";
        }
    }
}
}
