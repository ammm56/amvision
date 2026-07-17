using System;
using System.Collections.Generic;
using System.Drawing;
using System.IO;
using System.Threading;
using System.Threading.Tasks;
using Amvar.Vision;
using Amvar.Vision.Tools;

namespace AMVision.Console
{
    /// <summary>
    /// 控制台程序入口，负责加载配置并执行代码中手动启用的 SDK 调用。
    /// </summary>
    internal static class Program
    {
        /// <summary>
        /// Workflow runtime 配置 key，对应 Config/config*.json 中 runtimes[].name。
        /// </summary>
        private const string RuntimeName = "新建应用yolo11m_barqrcode";

        /// <summary>
        /// TriggerSource 配置 key，对应 Config/config*.json 中 trigger_sources[].name。
        /// </summary>
        private const string TriggerSourceName = "ZeroMQ 图片触发 新建应用yolo11m_barqrcode runtime";

        /// <summary>
        /// Model deployment 配置 key，对应 Config/config*.json 中 model_deployments[].name。
        /// </summary>
        private const string ModelDeploymentName = "yolo11-m-20260630190724 model-build-c8d6e4f701fc_2";

        /// <summary>
        /// 直接按后端资源 id 调用时使用；与 name 调用入口严格分开。
        /// </summary>
        private const string WorkflowRuntimeId = "workflow-runtime-768e3187953642e9a5a85353ffd96881";
        private const string TriggerSourceId = "zeromq-workflow-runtime-768e3187953642e9a5a85353ffd96881";
        private const string DeploymentInstanceId = "deployment-instance-8a186ddbab564e86a1649c16965ffa0f";
        private const string SyncRuntimeMode = "sync";

        /// <summary>
        /// 调试图片路径；相对路径会按控制台当前工作目录和配置文件位置解析。
        /// </summary>
        private const string ImagePath = @"Resources\Img\qrcode50.jpg";

        /// <summary>
        /// 调试用 WorkflowRun id，手动替换为真实返回值。
        /// </summary>
        private const string WorkflowRunId = "workflow-run-xxx";

        /// <summary>
        /// 调试用模型异步推理任务 id，手动替换为真实返回值。
        /// </summary>
        private const string ModelInferenceTaskId = "inference-task-xxx";

        /// <summary>
        /// 调试用模型推理 input_uri，手动替换为后端可读取的真实 URI。
        /// </summary>
        private const string ModelDeploymentInputUri = "runtime/inputs/image.jpg";

        /// <summary>
        /// 调试用模型推理 input_file_id，手动替换为真实文件 id。
        /// </summary>
        private const string ModelDeploymentInputFileId = "project-file-xxx";

        /// <summary>
        /// 调试图片默认 media type。
        /// </summary>
        private const string ImageMediaType = "image/jpeg";

        /// <summary>
        /// 程序入口。异常内容保持英文，避免 Windows 控制台编码差异导致乱码。
        /// </summary>
        /// <returns>进程退出码；0 表示成功。</returns>
        private static int Main()
        {
            try
            {
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
        /// SDK 调试入口。需要调用哪个接口，就取消对应代码行的注释。
        /// </summary>
        /// <param name="cancellationToken">取消信号。</param>
        private static async Task MainAsync(CancellationToken cancellationToken)
        {
            using (var runner = AMVisionOperationRunner.CreateDefault())
            {
                var runtimeNames = runner.RuntimeNames;
                var triggerSourceNames = runner.TriggerSourceNames;
                var modelDeploymentNames = runner.ModelDeploymentNames;
                _ = WorkflowRuntimeId;
                _ = TriggerSourceId;
                _ = DeploymentInstanceId;
                _ = SyncRuntimeMode;

                await Task.CompletedTask.ConfigureAwait(false);

                // 系统配置
                //var systemConfig = await runner.GetSystemConfigResponseAsync(cancellationToken).ConfigureAwait(false);

                // Model deployment 查询和管理。
                var deploymentStatus = await runner.GetModelDeploymentRuntimeStatusAsync(ModelDeploymentName, cancellationToken).ConfigureAwait(false);
                var deploymentHealth = await runner.GetModelDeploymentRuntimeHealthAsync(ModelDeploymentName, cancellationToken).ConfigureAwait(false);
                //var deploymentStart = await runner.StartModelDeploymentRuntimeAsync(ModelDeploymentName, cancellationToken).ConfigureAwait(false);
                //var deploymentStartSucceeded = deploymentStart.IsSuccessStatusCode;
                //var deploymentStop = await runner.StopModelDeploymentRuntimeAsync(ModelDeploymentName, cancellationToken).ConfigureAwait(false);
                //var deploymentWarmup = await runner.WarmupModelDeploymentRuntimeAsync(ModelDeploymentName, cancellationToken).ConfigureAwait(false);
                //var deploymentReset = await runner.ResetModelDeploymentRuntimeAsync(ModelDeploymentName, cancellationToken).ConfigureAwait(false);

                // Model deployment 同步推理
                //var deploymentInvoke = await runner.InvokeConfiguredModelDeploymentAsync(ModelDeploymentName, cancellationToken).ConfigureAwait(false);
                //var deploymentInvokeByBase64 = await runner.InvokeModelDeploymentWithImageBase64Async(ModelDeploymentName, LoadImageBase64(), cancellationToken).ConfigureAwait(false);
                //var deploymentInvokeByBytes = await runner.InvokeModelDeploymentWithImageBytesAsync(ModelDeploymentName, LoadImageBytes(), Path.GetFileName(ImagePath), ImageMediaType, cancellationToken).ConfigureAwait(false);
                //var deploymentInvokeByFile = await runner.InvokeModelDeploymentWithImageFromFileAsync(ModelDeploymentName, ImagePath, ImageMediaType, cancellationToken).ConfigureAwait(false);
                //var deploymentInvokeByInputFileId = await runner.InvokeModelDeploymentWithInputFileIdAsync(ModelDeploymentName, ModelDeploymentInputFileId, cancellationToken).ConfigureAwait(false);
                //var deploymentInvokeByInputUri = await runner.InvokeModelDeploymentWithInputUriAsync(ModelDeploymentName, ModelDeploymentInputUri, cancellationToken).ConfigureAwait(false);

                // Model deployment 异步推理任务
                //var deploymentRun = await runner.RunConfiguredModelDeploymentAsync(ModelDeploymentName, cancellationToken).ConfigureAwait(false);
                //var deploymentRunByBase64 = await runner.RunModelDeploymentWithImageBase64Async(ModelDeploymentName, LoadImageBase64(), cancellationToken).ConfigureAwait(false);
                //var deploymentRunByBytes = await runner.RunModelDeploymentWithImageBytesAsync(ModelDeploymentName, LoadImageBytes(), Path.GetFileName(ImagePath), ImageMediaType, cancellationToken).ConfigureAwait(false);
                //var deploymentRunByFile = await runner.RunModelDeploymentWithImageFromFileAsync(ModelDeploymentName, ImagePath, ImageMediaType, cancellationToken).ConfigureAwait(false);
                //var deploymentRunByInputFileId = await runner.RunModelDeploymentWithInputFileIdAsync(ModelDeploymentName, ModelDeploymentInputFileId, cancellationToken).ConfigureAwait(false);
                //var deploymentRunByInputUri = await runner.RunModelDeploymentWithInputUriAsync(ModelDeploymentName, ModelDeploymentInputUri, cancellationToken).ConfigureAwait(false);
                //var modelInferenceTask = await runner.GetModelInferenceTaskAsync(ModelDeploymentName, ModelInferenceTaskId, includeEvents: true, cancellationToken: cancellationToken).ConfigureAwait(false);
                //var modelInferenceTaskResult = await runner.GetModelInferenceTaskResultAsync(ModelDeploymentName, ModelInferenceTaskId, cancellationToken).ConfigureAwait(false);

                // Model deployment 直接按 deployment_instance_id 调用；同步、异步配置不会互相猜测。
                //var deploymentStatusById = await runner.GetModelDeploymentRuntimeStatusByIdAsync(DeploymentInstanceId, SyncRuntimeMode, cancellationToken).ConfigureAwait(false);
                //var deploymentHealthById = await runner.GetModelDeploymentRuntimeHealthByIdAsync(DeploymentInstanceId, SyncRuntimeMode, cancellationToken).ConfigureAwait(false);
                //var deploymentStartById = await runner.StartModelDeploymentRuntimeByIdAsync(DeploymentInstanceId, SyncRuntimeMode, cancellationToken).ConfigureAwait(false);
                //var deploymentStopById = await runner.StopModelDeploymentRuntimeByIdAsync(DeploymentInstanceId, SyncRuntimeMode, cancellationToken).ConfigureAwait(false);
                //var deploymentResetById = await runner.ResetModelDeploymentRuntimeByIdAsync(DeploymentInstanceId, SyncRuntimeMode, cancellationToken).ConfigureAwait(false);
                //var deploymentWarmupById = await runner.WarmupModelDeploymentRuntimeByIdAsync(DeploymentInstanceId, SyncRuntimeMode, cancellationToken).ConfigureAwait(false);
                //var deploymentInvokeById = await runner.InvokeConfiguredModelDeploymentByIdAsync(DeploymentInstanceId, cancellationToken).ConfigureAwait(false);
                //var deploymentInvokeBase64ById = await runner.InvokeModelDeploymentWithImageBase64ByIdAsync(DeploymentInstanceId, LoadImageBase64(), cancellationToken).ConfigureAwait(false);
                //var deploymentInvokeBytesById = await runner.InvokeModelDeploymentWithImageBytesByIdAsync(DeploymentInstanceId, LoadImageBytes(), Path.GetFileName(ImagePath), ImageMediaType, cancellationToken).ConfigureAwait(false);
                //var deploymentInvokeFileById = await runner.InvokeModelDeploymentWithImageFromFileByIdAsync(DeploymentInstanceId, ImagePath, ImageMediaType, cancellationToken).ConfigureAwait(false);
                //var deploymentInvokeFileIdById = await runner.InvokeModelDeploymentWithInputFileIdByIdAsync(DeploymentInstanceId, ModelDeploymentInputFileId, cancellationToken).ConfigureAwait(false);
                //var deploymentInvokeUriById = await runner.InvokeModelDeploymentWithInputUriByIdAsync(DeploymentInstanceId, ModelDeploymentInputUri, cancellationToken).ConfigureAwait(false);
                //var deploymentRunById = await runner.RunConfiguredModelDeploymentByIdAsync(DeploymentInstanceId, cancellationToken).ConfigureAwait(false);
                //var deploymentRunBase64ById = await runner.RunModelDeploymentWithImageBase64ByIdAsync(DeploymentInstanceId, LoadImageBase64(), cancellationToken).ConfigureAwait(false);
                //var deploymentRunBytesById = await runner.RunModelDeploymentWithImageBytesByIdAsync(DeploymentInstanceId, LoadImageBytes(), Path.GetFileName(ImagePath), ImageMediaType, cancellationToken).ConfigureAwait(false);
                //var deploymentRunFileById = await runner.RunModelDeploymentWithImageFromFileByIdAsync(DeploymentInstanceId, ImagePath, ImageMediaType, cancellationToken).ConfigureAwait(false);
                //var deploymentRunFileIdById = await runner.RunModelDeploymentWithInputFileIdByIdAsync(DeploymentInstanceId, ModelDeploymentInputFileId, cancellationToken).ConfigureAwait(false);
                //var deploymentRunUriById = await runner.RunModelDeploymentWithInputUriByIdAsync(DeploymentInstanceId, ModelDeploymentInputUri, cancellationToken).ConfigureAwait(false);
                //var modelInferenceTaskById = await runner.GetModelInferenceTaskByIdAsync(DeploymentInstanceId, ModelInferenceTaskId, includeEvents: true, cancellationToken: cancellationToken).ConfigureAwait(false);
                //var modelInferenceTaskResultById = await runner.GetModelInferenceTaskResultByIdAsync(DeploymentInstanceId, ModelInferenceTaskId, cancellationToken).ConfigureAwait(false);

                // Workflow runtime 查询和管理
                //var projectRuntimes = await runner.ListProjectRuntimesAsync(RuntimeName, cancellationToken).ConfigureAwait(false);
                //var runtime = await runner.GetRuntimeAsync(RuntimeName, cancellationToken).ConfigureAwait(false);
                //var runtimeHealth = await runner.GetRuntimeHealthAsync(RuntimeName, cancellationToken).ConfigureAwait(false);
                //var runtimeStart = await runner.StartRuntimeAsync(RuntimeName, cancellationToken).ConfigureAwait(false);
                //var runtimeStop = await runner.StopRuntimeAsync(RuntimeName, cancellationToken).ConfigureAwait(false);
                //var runtimeRestart = await runner.RestartRuntimeAsync(RuntimeName, cancellationToken).ConfigureAwait(false);
                //var runtimeInstances = await runner.ListRuntimeInstancesAsync(RuntimeName, cancellationToken).ConfigureAwait(false);
                //var runtimeEvents = await runner.GetRuntimeEventsAsync(RuntimeName, cancellationToken).ConfigureAwait(false);
                //var runtimeFlowCheck = await runner.CheckRuntimeFlowAsync(RuntimeName, cancellationToken).ConfigureAwait(false);

                // Workflow runtime 同步调用
                //var runtimeInvoke = await runner.InvokeRuntimeAppResultAsync(RuntimeName, cancellationToken).ConfigureAwait(false);
                //var runtimeInvokeByBase64 = await runner.InvokeRuntimeAppResultWithImageBase64Async(RuntimeName, LoadImageBase64(), ImageMediaType, cancellationToken).ConfigureAwait(false);
                //var runtimeInvokeByBytes = await runner.InvokeRuntimeAppResultWithImageBytesAsync(RuntimeName, LoadImageBytes(), ImageMediaType, cancellationToken).ConfigureAwait(false);
                //var runtimeInvokeByFile = await runner.InvokeRuntimeAppResultWithImageFromFileAsync(RuntimeName, ImagePath, ImageMediaType, cancellationToken).ConfigureAwait(false);

                // Workflow runtime 异步任务
                //var runtimeRun = await runner.RunRuntimeAsync(RuntimeName, cancellationToken).ConfigureAwait(false);
                //var runtimeRunByBase64 = await runner.RunRuntimeWithImageBase64Async(RuntimeName, LoadImageBase64(), ImageMediaType, cancellationToken).ConfigureAwait(false);
                //var runtimeRunByBytes = await runner.RunRuntimeWithImageBytesAsync(RuntimeName, LoadImageBytes(), ImageMediaType, cancellationToken).ConfigureAwait(false);
                //var runtimeRunByFile = await runner.RunRuntimeWithImageFromFileAsync(RuntimeName, ImagePath, ImageMediaType, cancellationToken).ConfigureAwait(false);
                //var workflowRun = await runner.GetWorkflowRunAsync(WorkflowRunId, cancellationToken).ConfigureAwait(false);
                //var workflowRunCancel = await runner.CancelWorkflowRunAsync(WorkflowRunId, cancellationToken).ConfigureAwait(false);
                //var workflowRunEvents = await runner.GetWorkflowRunEventsAsync(RuntimeName, WorkflowRunId, cancellationToken).ConfigureAwait(false);

                // Workflow runtime 直接按 workflow_runtime_id 调用。
                //var projectRuntimesById = await runner.ListProjectRuntimesByIdAsync(WorkflowRuntimeId, cancellationToken).ConfigureAwait(false);
                //var runtimeById = await runner.GetRuntimeByIdAsync(WorkflowRuntimeId, cancellationToken).ConfigureAwait(false);
                //var runtimeHealthById = await runner.GetRuntimeHealthByIdAsync(WorkflowRuntimeId, cancellationToken).ConfigureAwait(false);
                //var runtimeStartById = await runner.StartRuntimeByIdAsync(WorkflowRuntimeId, cancellationToken).ConfigureAwait(false);
                //var runtimeStopById = await runner.StopRuntimeByIdAsync(WorkflowRuntimeId, cancellationToken).ConfigureAwait(false);
                //var runtimeRestartById = await runner.RestartRuntimeByIdAsync(WorkflowRuntimeId, cancellationToken).ConfigureAwait(false);
                //var runtimeInstancesById = await runner.ListRuntimeInstancesByIdAsync(WorkflowRuntimeId, cancellationToken).ConfigureAwait(false);
                //var runtimeEventsById = await runner.GetRuntimeEventsByIdAsync(WorkflowRuntimeId, cancellationToken).ConfigureAwait(false);
                //var runtimeFlowCheckById = await runner.CheckRuntimeFlowByIdAsync(WorkflowRuntimeId, cancellationToken).ConfigureAwait(false);
                //var runtimeInvokeById = await runner.InvokeRuntimeAppResultByIdAsync(WorkflowRuntimeId, cancellationToken).ConfigureAwait(false);
                //var runtimeInvokeBase64ById = await runner.InvokeRuntimeAppResultWithImageBase64ByIdAsync(WorkflowRuntimeId, LoadImageBase64(), ImageMediaType, cancellationToken).ConfigureAwait(false);
                //var runtimeInvokeBytesById = await runner.InvokeRuntimeAppResultWithImageBytesByIdAsync(WorkflowRuntimeId, LoadImageBytes(), ImageMediaType, cancellationToken).ConfigureAwait(false);
                //var runtimeInvokeFileById = await runner.InvokeRuntimeAppResultWithImageFromFileByIdAsync(WorkflowRuntimeId, ImagePath, ImageMediaType, cancellationToken).ConfigureAwait(false);
                //var runtimeRunById = await runner.RunRuntimeByIdAsync(WorkflowRuntimeId, cancellationToken).ConfigureAwait(false);
                //var runtimeRunBase64ById = await runner.RunRuntimeWithImageBase64ByIdAsync(WorkflowRuntimeId, LoadImageBase64(), ImageMediaType, cancellationToken).ConfigureAwait(false);
                //var runtimeRunBytesById = await runner.RunRuntimeWithImageBytesByIdAsync(WorkflowRuntimeId, LoadImageBytes(), ImageMediaType, cancellationToken).ConfigureAwait(false);
                //var runtimeRunFileById = await runner.RunRuntimeWithImageFromFileByIdAsync(WorkflowRuntimeId, ImagePath, ImageMediaType, cancellationToken).ConfigureAwait(false);
                //var workflowRunEventsById = await runner.GetWorkflowRunEventsByRuntimeIdAsync(WorkflowRuntimeId, WorkflowRunId, cancellationToken).ConfigureAwait(false);

                // TriggerSource 查询和管理
                //var triggerSources = await runner.ListTriggerSourcesAsync(RuntimeName, cancellationToken).ConfigureAwait(false);
                //var triggerSource = await runner.GetTriggerSourceAsync(TriggerSourceName, cancellationToken).ConfigureAwait(false);
                //var triggerSourceEnable = await runner.EnableTriggerSourceAsync(TriggerSourceName, cancellationToken).ConfigureAwait(false);
                //var triggerSourceDisable = await runner.DisableTriggerSourceAsync(TriggerSourceName, cancellationToken).ConfigureAwait(false);
                //var triggerSourceHealth = await runner.GetTriggerSourceHealthAsync(TriggerSourceName, cancellationToken).ConfigureAwait(false);

                // ZeroMQ 通用事件和图片触发
                //var zeroMqEvent = runner.InvokeZeroMqEvent(TriggerSourceName, new Dictionary<string, object?> { { "source", "dotnet-console" } }, cancellationToken);
                //var zeroMqConfiguredImage = runner.InvokeConfiguredZeroMqImage(TriggerSourceName, cancellationToken);
                //var zeroMqImageByFile = runner.InvokeZeroMqImageFromFile(TriggerSourceName, ImagePath, ImageMediaType, cancellationToken);
                //var zeroMqImageByBytes = runner.InvokeZeroMqImageBytes(TriggerSourceName, LoadImageBytes(), ImageMediaType, cancellationToken);
                //var zeroMqImageByBase64 = runner.InvokeZeroMqImageBase64(TriggerSourceName, LoadImageBase64(), ImageMediaType, cancellationToken);

                // ZeroMQ BGR24 触发
                //var bgr24Frame = LoadBgr24ImageFrame();
                //var zeroMqBgr24 = runner.InvokeZeroMqBgr24(TriggerSourceName, bgr24Frame.Bytes, bgr24Frame.Width, bgr24Frame.Height, cancellationToken);
                //var zeroMqBgr24ByFile = runner.InvokeZeroMqBgr24FromFile(TriggerSourceName, ImagePath, cancellationToken);
                //var zeroMqConfiguredBgr24 = runner.InvokeConfiguredZeroMqBgr24Image(TriggerSourceName, cancellationToken);
                //using (var bitmap = LoadBitmap())
                //{
                //    var zeroMqBgr24ByBitmap = runner.InvokeZeroMqBgr24FromBitmap(TriggerSourceName, bitmap, cancellationToken);
                //}

                // TriggerSource 直接按 trigger_source_id 调用；列表接口按 workflow_runtime_id 调用。
                //var triggerSourcesByRuntimeId = await runner.ListTriggerSourcesByRuntimeIdAsync(WorkflowRuntimeId, cancellationToken).ConfigureAwait(false);
                //var triggerSourceById = await runner.GetTriggerSourceByIdAsync(TriggerSourceId, cancellationToken).ConfigureAwait(false);
                //var triggerSourceEnableById = await runner.EnableTriggerSourceByIdAsync(TriggerSourceId, cancellationToken).ConfigureAwait(false);
                //var triggerSourceDisableById = await runner.DisableTriggerSourceByIdAsync(TriggerSourceId, cancellationToken).ConfigureAwait(false);
                //var triggerSourceHealthById = await runner.GetTriggerSourceHealthByIdAsync(TriggerSourceId, cancellationToken).ConfigureAwait(false);
                //var zeroMqEventById = runner.InvokeZeroMqEventById(TriggerSourceId, new Dictionary<string, object?> { { "source", "dotnet-console" } }, cancellationToken);
                //var zeroMqConfiguredImageById = runner.InvokeConfiguredZeroMqImageById(TriggerSourceId, cancellationToken);
                //var zeroMqImageFileById = runner.InvokeZeroMqImageFromFileById(TriggerSourceId, ImagePath, ImageMediaType, cancellationToken);
                //var zeroMqImageBytesById = runner.InvokeZeroMqImageBytesById(TriggerSourceId, LoadImageBytes(), ImageMediaType, cancellationToken);
                //var zeroMqImageBase64ById = runner.InvokeZeroMqImageBase64ById(TriggerSourceId, LoadImageBase64(), ImageMediaType, cancellationToken);
                //var zeroMqBgr24FrameById = LoadBgr24ImageFrame();
                //var zeroMqBgr24ById = runner.InvokeZeroMqBgr24ById(TriggerSourceId, zeroMqBgr24FrameById.Bytes, zeroMqBgr24FrameById.Width, zeroMqBgr24FrameById.Height, cancellationToken);
                //var zeroMqBgr24FileById = runner.InvokeZeroMqBgr24FromFileById(TriggerSourceId, ImagePath, cancellationToken);
                //var zeroMqConfiguredBgr24ById = runner.InvokeConfiguredZeroMqBgr24ImageById(TriggerSourceId, cancellationToken);
                //using (var bitmapById = LoadBitmap())
                //{
                //    var zeroMqBgr24BitmapById = runner.InvokeZeroMqBgr24FromBitmapById(TriggerSourceId, bitmapById, cancellationToken);
                //}

                // 图片转换工具
                //var imageFormat = ImageConversionTools.InferFormatFromPath(ImagePath);
                //var mediaType = ImageConversionTools.GetMediaType(imageFormat);
                //var imageBase64 = ImageConversionTools.ImageFileToBase64(ImagePath);
                //var imageDataUrl = ImageConversionTools.ImageFileToDataUrl(ImagePath);
                //var imageFrame = ImageConversionTools.ImageFileToBgr24(ImagePath);
                //var imageBytes = ImageConversionTools.ConvertImageFileToBytes(ImagePath, ImageFileFormat.JPEG, jpegQuality: 85L);
                //var bgr24ImageBytes = ImageConversionTools.Bgr24ToImageBytes(imageFrame.Bytes, imageFrame.Width, imageFrame.Height, ImageFileFormat.JPEG, jpegQuality: 85L);
            }

            if (!System.Console.IsInputRedirected)
            {
                System.Console.ReadKey(intercept: true);
            }
        }

        /// <summary>
        /// 读取调试图片为 data URL base64，适合 Workflow App 的 image-base64 输入。
        /// </summary>
        /// <returns>带 media type 的 data URL base64。</returns>
        private static string LoadImageBase64()
        {
            var imageBase64 = ImageConversionTools.ImageFileToDataUrl(ImagePath);
            return imageBase64;
        }

        /// <summary>
        /// 读取调试图片原始编码 bytes。
        /// </summary>
        /// <returns>图片文件 bytes。</returns>
        private static byte[] LoadImageBytes()
        {
            var imageBytes = File.ReadAllBytes(ImagePath);
            return imageBytes;
        }

        /// <summary>
        /// 读取调试图片并转换为 BGR24 raw frame。
        /// </summary>
        /// <returns>BGR24 raw frame。</returns>
        private static Bgr24ImageFrame LoadBgr24ImageFrame()
        {
            var frame = ImageConversionTools.ImageFileToBgr24(ImagePath);
            return frame;
        }

        /// <summary>
        /// 读取调试图片为 Bitmap；调用方负责释放返回对象。
        /// </summary>
        /// <returns>Bitmap 图片对象。</returns>
        private static Bitmap LoadBitmap()
        {
            var bitmap = new Bitmap(ImagePath);
            return bitmap;
        }
    }
}
