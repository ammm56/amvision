using System;
using System.IO;
using Amvision.Workflows.Net461Console.Model;

namespace Amvision.Workflows.Net461Console.Runtime;

/// <summary>
/// WorkflowAppRuntime 控制和调用操作集合。
/// </summary>
internal sealed partial class WorkflowRuntimeOperations
{
    /// <summary>
    /// 复用的 HTTP SDK client。
    /// </summary>
    private readonly AmvisionWorkflowClient client;

    /// <summary>
    /// runtime 和 TriggerSource 配置索引。
    /// </summary>
    private readonly WorkflowConfigurationCatalog catalog;

    /// <summary>
    /// 初始化 runtime 操作对象。
    /// </summary>
    /// <param name="client">HTTP SDK client。</param>
    /// <param name="catalog">配置 catalog。</param>
    public WorkflowRuntimeOperations(AmvisionWorkflowClient client, WorkflowConfigurationCatalog catalog)
    {
        this.client = client ?? throw new ArgumentNullException(nameof(client));
        this.catalog = catalog ?? throw new ArgumentNullException(nameof(catalog));
    }

    /// <summary>
    /// 按 runtime key 获取配置。
    /// </summary>
    /// <param name="runtimeName">runtime key。</param>
    /// <returns>runtime 配置。</returns>
    private ConfiguredRuntime GetConfiguredRuntime(string runtimeName)
    {
        return catalog.GetRuntime(runtimeName);
    }

    /// <summary>
    /// 获取后端 runtime id；为空说明前端配置未同步到 config_*.json。
    /// </summary>
    /// <param name="configuredRuntime">runtime 配置。</param>
    /// <returns>workflow_runtime_id。</returns>
    private static string RequireRuntimeId(ConfiguredRuntime configuredRuntime)
    {
        return ConfigValidation.RequireText(
            configuredRuntime.Runtime.WorkflowRuntimeId,
            $"{configuredRuntime.Runtime.Name}.workflow_runtime_id");
    }

    /// <summary>
    /// 判断当前 runtime 配置是否带图片输入。
    /// </summary>
    /// <param name="configuredRuntime">runtime 配置。</param>
    /// <returns>带图片路径时返回 true。</returns>
    private static bool HasImageInput(ConfiguredRuntime configuredRuntime)
    {
        return ConfigValidation.NormalizeOptional(configuredRuntime.Invoke.ImagePath) is not null;
    }

    /// <summary>
    /// 将配置文件中的相对路径解析为绝对路径。
    /// </summary>
    /// <param name="configuredRuntime">runtime 配置。</param>
    /// <param name="configuredPath">配置中的路径。</param>
    /// <returns>绝对路径。</returns>
    private static string ResolveConfiguredPath(ConfiguredRuntime configuredRuntime, string configuredPath)
    {
        var normalizedPath = configuredPath.Trim();
        return Path.IsPathRooted(normalizedPath)
            ? normalizedPath
            : Path.GetFullPath(Path.Combine(Path.GetDirectoryName(configuredRuntime.SourceFile) ?? ".", normalizedPath));
    }

    /// <summary>
    /// 按图片扩展名推断 HTTP image invoke 使用的 media type。
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
