using Amvision.Workflows.Net461Console.Model;

namespace Amvision.Workflows.Net461Console.Runtime;

/// <summary>
/// 构建异步 WorkflowRun 提交请求。
/// </summary>
internal sealed partial class WorkflowRuntimeOperations
{
    /// <summary>
    /// 根据配置是否带图片路径自动选择 image-base64 或普通 JSON 请求。
    /// </summary>
    /// <param name="configuredRuntime">runtime 配置。</param>
    /// <param name="scenario">写入 execution_metadata 的场景名。</param>
    /// <returns>WorkflowRun 提交请求。</returns>
    private static WorkflowRuntimeInvokeRequest BuildWorkflowRunRequest(
        ConfiguredRuntime configuredRuntime,
        string scenario)
    {
        return HasImageInput(configuredRuntime)
            ? BuildImageInvokeRequest(configuredRuntime, scenario).ToWorkflowRuntimeInvokeRequest()
            : BuildJsonInvokeRequest(configuredRuntime, scenario);
    }
}
