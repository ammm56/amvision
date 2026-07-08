using Amvision.Workflows.Console.Tools;
using System;
using System.IO;
using System.Threading;
using System.Threading.Tasks;

namespace Amvision.Workflows.Console;

/// <summary>
/// 控制台程序入口，负责加载配置并执行代码中手动指定的调用方法。
/// </summary>
internal static class Program
{
    /// <summary>
    /// workflow app runtime 工作流应用调用使用
    /// 默认 runtime 配置 key；现场使用时按 Config/config_*.json 修改。
    /// </summary>
    private const string RuntimeName = "yolo11m_barqrcode_runtime";

    /// <summary>
    /// 触发调用 workflow app runtime 工作流应用调用使用
    /// 默认 TriggerSource 配置 key；现场使用时按 Config/config_*.json 修改。
    /// </summary>
    private const string TriggerSourceName = "yolo11m_barqrcode_zeromq";

    /// <summary>
    /// 直接调用部署的模型推理使用
    /// 默认模型 deployment 配置 key；现场使用时按 Config/config_*.json 修改。
    /// </summary>
    private const string ModelDeploymentName = "barcode_detector";

    /// <summary>
    /// 一般不会使用
    /// WorkflowAppRuntime 或 ZeroMQ 图片文件路径；调用 ImageFromFile 方法时填写。
    /// </summary>
    private const string ImagePath = "Resources\\Img\\qrcode50.jpg";
    /// <summary>
    /// 一般不会使用
    /// 已存在 WorkflowRun id；调用 GetWorkflowRunAsync 或 GetWorkflowRunEventsAsync 时填写。
    /// </summary>
    private const string WorkflowRunId = "workflow-run-xxx";
    /// <summary>
    /// 一般不会使用
    /// 已存在模型异步推理任务 id；调用 GetModelInferenceTaskAsync 或 GetModelInferenceTaskResultAsync 时填写。
    /// </summary>
    private const string ModelInferenceTaskId = "inference-task-xxx";
    /// <summary>
    /// 一般不会使用
    /// 后端可读取的模型部署 input_uri；调用 input_uri 方法时填写。
    /// </summary>
    private const string ModelDeploymentInputUri = "runtime/inputs/image.jpg";
    /// <summary>
    /// 一般不会使用
    /// 后端已登记的模型部署 input_file_id；调用 input_file_id 方法时填写。
    /// </summary>
    private const string ModelDeploymentInputFileId = "project-file-xxx";

    /// <summary>
    /// 现场相机或其他上游程序传入的 base64 图片；调用 ImageBase64 方法时填写。
    /// </summary>
    private static string ImageBase64 = "data:image/jpeg;base64,";

    /// <summary>
    /// 现场相机或其他上游程序传入的图片 bytes；调用 ImageBytes 方法时填写。
    /// </summary>
    private static byte[] ImageBytes = Array.Empty<byte>();

    /// <summary>
    /// 同步入口，桥接 async 主流程并统一输出错误。
    /// </summary>
    /// <returns>进程退出码。</returns>
    private static int Main()
    {
        try
        {
            ImageBase64 = ImageConversionTools.ImageFileToDataUrl(ImagePath);
            ImageBytes = File.ReadAllBytes(ConfiguredPathResolver.ResolveExistingFile(
                ImagePath,
                sourceFile: null,
                message: "Input image file does not exist."));
            MainAsync(CancellationToken.None).GetAwaiter().GetResult();
            return 0;
        }
        catch (Exception exception)
        {
            System.Console.Error.WriteLine(exception);
            return 1;
        }
    }

    /// <summary>
    /// 主执行流程；启动时加载全部 config_*.json，并调用代码中明确指定的方法。
    /// </summary>
    /// <param name="cancellationToken">取消信号。</param>
    private static async Task MainAsync(CancellationToken cancellationToken)
    {
        using var runner = WorkflowOperationRunner.CreateDefault();

        var runtimeNames = runner.RuntimeNames;
        var triggerSourceNames = runner.TriggerSourceNames;
        var modelDeploymentNames = runner.ModelDeploymentNames;

        // 后端统一配置：用于读取 backend-service 当前公开配置快照。
        //var systemConfig = await runner.GetSystemConfigAsync(cancellationToken).ConfigureAwait(false);

        // WorkflowAppRuntime：读取和控制。
        var runtimeHealth = await runner.GetRuntimeHealthAsync(RuntimeName, cancellationToken).ConfigureAwait(false);
        // runtimeHealth 可直接绑定到 WinForms/WPF 页面，或继续参与现场业务判断。
        //var runtime = await runner.GetRuntimeAsync(RuntimeName, cancellationToken).ConfigureAwait(false);
        //var runtimes = await runner.ListProjectRuntimesAsync(RuntimeName, cancellationToken).ConfigureAwait(false);
        //var startedRuntime = await runner.StartRuntimeAsync(RuntimeName, cancellationToken).ConfigureAwait(false);
        //var stoppedRuntime = await runner.StopRuntimeAsync(RuntimeName, cancellationToken).ConfigureAwait(false);
        //var restartedRuntime = await runner.RestartRuntimeAsync(RuntimeName, cancellationToken).ConfigureAwait(false);
        //var runtimeInstances = await runner.ListRuntimeInstancesAsync(RuntimeName, cancellationToken).ConfigureAwait(false);
        //var runtimeEvents = await runner.GetRuntimeEventsAsync(RuntimeName, cancellationToken).ConfigureAwait(false);
        //var checkResult = await runner.CheckRuntimeFlowAsync(RuntimeName, cancellationToken).ConfigureAwait(false);

        // WorkflowAppRuntime：同步 invoke
        //var appResult = await runner.InvokeRuntimeAppResultAsync(RuntimeName, cancellationToken).ConfigureAwait(false);
        //var workflowRun = await runner.RunRuntimeAsync(RuntimeName, cancellationToken).ConfigureAwait(false);
        var syncBase64Result = await runner.InvokeRuntimeAppResultWithImageBase64Async(RuntimeName, ImageBase64, mediaType: "image/jpeg", cancellationToken: cancellationToken).ConfigureAwait(false);
        var syncBytesResult = await runner.InvokeRuntimeAppResultWithImageBytesAsync(RuntimeName, ImageBytes, mediaType: "image/jpeg", cancellationToken: cancellationToken).ConfigureAwait(false);
        //var syncFileResult = await runner.InvokeRuntimeAppResultWithImageFromFileAsync(RuntimeName, ImagePath, cancellationToken: cancellationToken).ConfigureAwait(false);

        // WorkflowAppRuntime：异步 run
        //var asyncBase64Run = await runner.RunRuntimeWithImageBase64Async(RuntimeName, ImageBase64, mediaType: "image/jpeg", cancellationToken: cancellationToken).ConfigureAwait(false);
        //var asyncBytesRun = await runner.RunRuntimeWithImageBytesAsync(RuntimeName, ImageBytes, mediaType: "image/jpeg", cancellationToken: cancellationToken).ConfigureAwait(false);
        //var asyncFileRun = await runner.RunRuntimeWithImageFromFileAsync(RuntimeName, ImagePath, cancellationToken: cancellationToken).ConfigureAwait(false);
        //var existingWorkflowRun = await runner.GetWorkflowRunAsync(WorkflowRunId, cancellationToken).ConfigureAwait(false);
        //var canceledWorkflowRun = await runner.CancelWorkflowRunAsync(WorkflowRunId, cancellationToken).ConfigureAwait(false);
        //var workflowRunEvents = await runner.GetWorkflowRunEventsAsync(RuntimeName, WorkflowRunId, cancellationToken).ConfigureAwait(false);

        // TriggerSource：读取、启用、停用和 health。
        //var triggerSources = await runner.ListTriggerSourcesAsync(RuntimeName, cancellationToken).ConfigureAwait(false);
        //var triggerSource = await runner.GetTriggerSourceAsync(TriggerSourceName, cancellationToken).ConfigureAwait(false);
        //var enabledTriggerSource = await runner.EnableTriggerSourceAsync(TriggerSourceName, cancellationToken).ConfigureAwait(false);
        //var disabledTriggerSource = await runner.DisableTriggerSourceAsync(TriggerSourceName, cancellationToken).ConfigureAwait(false);
        var triggerHealth = await runner.GetTriggerSourceHealthAsync(TriggerSourceName, cancellationToken).ConfigureAwait(false);

        // ZeroMQ TriggerSource：纯事件和图片触发。
        //var eventResult = await runner.InvokeZeroMqEventAsync(TriggerSourceName, cancellationToken: cancellationToken).ConfigureAwait(false);
        //var configuredImageResult = await runner.InvokeZeroMqConfiguredImageAsync(TriggerSourceName, cancellationToken).ConfigureAwait(false);
        //var fileImageResult = await runner.InvokeZeroMqImageFromFileAsync(TriggerSourceName, ImagePath, cancellationToken: cancellationToken).ConfigureAwait(false);
        var bytesImageResult = await runner.InvokeZeroMqImageBytesAsync(TriggerSourceName, ImageBytes, mediaType: "image/jpeg", cancellationToken: cancellationToken).ConfigureAwait(false);
        var base64ImageResult = await runner.InvokeZeroMqImageBase64Async(TriggerSourceName, ImageBase64, mediaType: "image/jpeg", cancellationToken: cancellationToken).ConfigureAwait(false);

        // 模型 DeploymentInstance：runtime 启动、停止、重置、预热、状态和 health。
        //var startedModelRuntime = await runner.StartModelDeploymentRuntimeAsync(ModelDeploymentName, cancellationToken).ConfigureAwait(false);
        //var stoppedModelRuntime = await runner.StopModelDeploymentRuntimeAsync(ModelDeploymentName, cancellationToken).ConfigureAwait(false);
        //var resetModelRuntime = await runner.ResetModelDeploymentRuntimeAsync(ModelDeploymentName, cancellationToken).ConfigureAwait(false);
        //var warmedModelRuntime = await runner.WarmupModelDeploymentRuntimeAsync(ModelDeploymentName, cancellationToken).ConfigureAwait(false);
        var modelRuntimeStatus = await runner.GetModelDeploymentRuntimeStatusAsync(ModelDeploymentName, cancellationToken).ConfigureAwait(false);
        var modelRuntimeHealth = await runner.GetModelDeploymentRuntimeHealthAsync(ModelDeploymentName, cancellationToken).ConfigureAwait(false);

        // 模型 DeploymentInstance：同步推理。
        //var modelConfiguredSyncResult = await runner.InvokeConfiguredModelDeploymentAsync(ModelDeploymentName, cancellationToken).ConfigureAwait(false);
        var modelBase64SyncResult = await runner.InvokeModelDeploymentWithImageBase64Async(ModelDeploymentName, ImageBase64, cancellationToken).ConfigureAwait(false);
        var modelBytesSyncResult = await runner.InvokeModelDeploymentWithImageBytesAsync(ModelDeploymentName, ImageBytes, fileName: "camera.jpg", mediaType: "image/jpeg", cancellationToken: cancellationToken).ConfigureAwait(false);
        //var modelFileSyncResult = await runner.InvokeModelDeploymentWithImageFromFileAsync(ModelDeploymentName, ImagePath, cancellationToken: cancellationToken).ConfigureAwait(false);
        //var modelUriSyncResult = await runner.InvokeModelDeploymentWithInputUriAsync(ModelDeploymentName, ModelDeploymentInputUri, cancellationToken).ConfigureAwait(false);
        //var modelFileIdSyncResult = await runner.InvokeModelDeploymentWithInputFileIdAsync(ModelDeploymentName, ModelDeploymentInputFileId, cancellationToken).ConfigureAwait(false);

        // 模型 DeploymentInstance：异步 inference task。
        //var modelConfiguredTask = await runner.RunConfiguredModelDeploymentAsync(ModelDeploymentName, cancellationToken).ConfigureAwait(false);
        //var modelBase64Task = await runner.RunModelDeploymentWithImageBase64Async(ModelDeploymentName, ImageBase64, cancellationToken).ConfigureAwait(false);
        //var modelBytesTask = await runner.RunModelDeploymentWithImageBytesAsync(ModelDeploymentName, ImageBytes, fileName: "camera.jpg", mediaType: "image/jpeg", cancellationToken: cancellationToken).ConfigureAwait(false);
        //var modelFileTask = await runner.RunModelDeploymentWithImageFromFileAsync(ModelDeploymentName, ImagePath, cancellationToken: cancellationToken).ConfigureAwait(false);
        //var modelUriTask = await runner.RunModelDeploymentWithInputUriAsync(ModelDeploymentName, ModelDeploymentInputUri, cancellationToken).ConfigureAwait(false);
        //var modelFileIdTask = await runner.RunModelDeploymentWithInputFileIdAsync(ModelDeploymentName, ModelDeploymentInputFileId, cancellationToken).ConfigureAwait(false);
        //var modelTaskDetail = await runner.GetModelInferenceTaskAsync(ModelDeploymentName, ModelInferenceTaskId, includeEvents: true, cancellationToken: cancellationToken).ConfigureAwait(false);
        //var modelTaskResult = await runner.GetModelInferenceTaskResultAsync(ModelDeploymentName, ModelInferenceTaskId, cancellationToken).ConfigureAwait(false);
    }
}
