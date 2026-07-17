using System.Collections.Generic;
using System.IO;
using System.Threading;
using System.Threading.Tasks;
using Amvar.Vision;
using static AMVision.Console.SdkCallInputs;

namespace AMVision.Console
{
    /// <summary>
    /// 默认调用方式：使用 SDK 配置中的可读 key name。
    /// 示例严格按模型、Workflow App Runtime、TriggerSource 的操作顺序排列。
    /// </summary>
    internal static class KeyNameSdkCalls
    {
        private const string ModelDeploymentName = "yolo11-m-20260630190724 model-build-c8d6e4f701fc_2";
        private const string RuntimeName = "新建应用yolo11m_barqrcode";
        private const string TriggerSourceName = "ZeroMQ 图片触发 新建应用yolo11m_barqrcode runtime";

        public static async Task RunAsync(
            AMVisionOperationRunner runner,
            CancellationToken cancellationToken)
        {
            // 各分组内默认不发请求。按需取消具体调用行的注释，避免调试程序意外改变现场状态。
            await RunModelDeploymentCallsAsync(runner, cancellationToken).ConfigureAwait(false);
            await RunWorkflowRuntimeCallsAsync(runner, cancellationToken).ConfigureAwait(false);
            await RunTriggerSourceCallsAsync(runner, cancellationToken).ConfigureAwait(false);
        }

        private static async Task RunModelDeploymentCallsAsync(
            AMVisionOperationRunner runner,
            CancellationToken cancellationToken)
        {
            // 管理与状态（强类型响应；非 2xx 抛出 AMVisionApiException）
            var start = await runner.StartModelDeploymentRuntimeAsync(ModelDeploymentName, cancellationToken).ConfigureAwait(false);
            var warmup = await runner.WarmupModelDeploymentRuntimeAsync(ModelDeploymentName, cancellationToken).ConfigureAwait(false);
            //var reset = await runner.ResetModelDeploymentRuntimeAsync(ModelDeploymentName, cancellationToken).ConfigureAwait(false);
            var stop = await runner.StopModelDeploymentRuntimeAsync(ModelDeploymentName, cancellationToken).ConfigureAwait(false);
            var status = await runner.GetModelDeploymentRuntimeStatusAsync(ModelDeploymentName, cancellationToken).ConfigureAwait(false);
            var health = await runner.GetModelDeploymentRuntimeHealthAsync(ModelDeploymentName, cancellationToken).ConfigureAwait(false);

            // 同步推理
            //var invoke = await runner.InvokeConfiguredModelDeploymentAsync(ModelDeploymentName, cancellationToken).ConfigureAwait(false);
            var invokeBase64 = await runner.InvokeModelDeploymentWithImageBase64Async(ModelDeploymentName, LoadImageBase64(), cancellationToken).ConfigureAwait(false);
            var invokeBytes = await runner.InvokeModelDeploymentWithImageBytesAsync(ModelDeploymentName, LoadImageBytes(), Path.GetFileName(ImagePath), ImageMediaType, cancellationToken).ConfigureAwait(false);
            //var invokeFile = await runner.InvokeModelDeploymentWithImageFromFileAsync(ModelDeploymentName, ImagePath, ImageMediaType, cancellationToken).ConfigureAwait(false);
            //var invokeFileId = await runner.InvokeModelDeploymentWithInputFileIdAsync(ModelDeploymentName, ModelDeploymentInputFileId, cancellationToken).ConfigureAwait(false);
            //var invokeUri = await runner.InvokeModelDeploymentWithInputUriAsync(ModelDeploymentName, ModelDeploymentInputUri, cancellationToken).ConfigureAwait(false);

            // 异步推理任务
            //var run = await runner.RunConfiguredModelDeploymentAsync(ModelDeploymentName, cancellationToken).ConfigureAwait(false);
            //var runBase64 = await runner.RunModelDeploymentWithImageBase64Async(ModelDeploymentName, LoadImageBase64(), cancellationToken).ConfigureAwait(false);
            //var runBytes = await runner.RunModelDeploymentWithImageBytesAsync(ModelDeploymentName, LoadImageBytes(), Path.GetFileName(ImagePath), ImageMediaType, cancellationToken).ConfigureAwait(false);
            //var runFile = await runner.RunModelDeploymentWithImageFromFileAsync(ModelDeploymentName, ImagePath, ImageMediaType, cancellationToken).ConfigureAwait(false);
            //var runFileId = await runner.RunModelDeploymentWithInputFileIdAsync(ModelDeploymentName, ModelDeploymentInputFileId, cancellationToken).ConfigureAwait(false);
            //var runUri = await runner.RunModelDeploymentWithInputUriAsync(ModelDeploymentName, ModelDeploymentInputUri, cancellationToken).ConfigureAwait(false);
            //var task = await runner.GetModelInferenceTaskAsync(ModelDeploymentName, ModelInferenceTaskId, includeEvents: true, cancellationToken: cancellationToken).ConfigureAwait(false);
            //var taskResult = await runner.GetModelInferenceTaskResultAsync(ModelDeploymentName, ModelInferenceTaskId, cancellationToken).ConfigureAwait(false);

            await Task.CompletedTask.ConfigureAwait(false);
        }

        private static async Task RunWorkflowRuntimeCallsAsync(
            AMVisionOperationRunner runner,
            CancellationToken cancellationToken)
        {
            // 管理与状态
            //var projectRuntimes = await runner.ListProjectRuntimesAsync(RuntimeName, cancellationToken).ConfigureAwait(false);
            var start = await runner.StartRuntimeAsync(RuntimeName, cancellationToken).ConfigureAwait(false);
            var stop = await runner.StopRuntimeAsync(RuntimeName, cancellationToken).ConfigureAwait(false);
            var runtime = await runner.GetRuntimeAsync(RuntimeName, cancellationToken).ConfigureAwait(false);
            var health = await runner.GetRuntimeHealthAsync(RuntimeName, cancellationToken).ConfigureAwait(false);
            //var restart = await runner.RestartRuntimeAsync(RuntimeName, cancellationToken).ConfigureAwait(false);
            //var instances = await runner.ListRuntimeInstancesAsync(RuntimeName, cancellationToken).ConfigureAwait(false);
            //var events = await runner.GetRuntimeEventsAsync(RuntimeName, cancellationToken).ConfigureAwait(false);
            //var flowCheck = await runner.CheckRuntimeFlowAsync(RuntimeName, cancellationToken).ConfigureAwait(false);

            // 同步调用
            //var invoke = await runner.InvokeRuntimeAppResultAsync(RuntimeName, cancellationToken).ConfigureAwait(false);
            var invokeBase64 = await runner.InvokeRuntimeAppResultWithImageBase64Async(RuntimeName, LoadImageBase64(), ImageMediaType, cancellationToken).ConfigureAwait(false);
            var invokeBytes = await runner.InvokeRuntimeAppResultWithImageBytesAsync(RuntimeName, LoadImageBytes(), ImageMediaType, cancellationToken).ConfigureAwait(false);
            //var invokeFile = await runner.InvokeRuntimeAppResultWithImageFromFileAsync(RuntimeName, ImagePath, ImageMediaType, cancellationToken).ConfigureAwait(false);

            // 异步任务
            //var run = await runner.RunRuntimeAsync(RuntimeName, cancellationToken).ConfigureAwait(false);
            //var runBase64 = await runner.RunRuntimeWithImageBase64Async(RuntimeName, LoadImageBase64(), ImageMediaType, cancellationToken).ConfigureAwait(false);
            //var runBytes = await runner.RunRuntimeWithImageBytesAsync(RuntimeName, LoadImageBytes(), ImageMediaType, cancellationToken).ConfigureAwait(false);
            //var runFile = await runner.RunRuntimeWithImageFromFileAsync(RuntimeName, ImagePath, ImageMediaType, cancellationToken).ConfigureAwait(false);
            //var workflowRun = await runner.GetWorkflowRunAsync(WorkflowRunId, cancellationToken).ConfigureAwait(false);
            //var cancel = await runner.CancelWorkflowRunAsync(WorkflowRunId, cancellationToken).ConfigureAwait(false);
            //var runEvents = await runner.GetWorkflowRunEventsAsync(RuntimeName, WorkflowRunId, cancellationToken).ConfigureAwait(false);

            await Task.CompletedTask.ConfigureAwait(false);
        }

        private static async Task RunTriggerSourceCallsAsync(
            AMVisionOperationRunner runner,
            CancellationToken cancellationToken)
        {
            // 管理与状态
            //var sources = await runner.ListTriggerSourcesAsync(RuntimeName, cancellationToken).ConfigureAwait(false);
            //var source = await runner.GetTriggerSourceAsync(TriggerSourceName, cancellationToken).ConfigureAwait(false);
            var enable = await runner.EnableTriggerSourceAsync(TriggerSourceName, cancellationToken).ConfigureAwait(false);
            var disable = await runner.DisableTriggerSourceAsync(TriggerSourceName, cancellationToken).ConfigureAwait(false);
            var health = await runner.GetTriggerSourceHealthAsync(TriggerSourceName, cancellationToken).ConfigureAwait(false);

            // ZeroMQ 事件与编码图片
            //var eventResult = runner.InvokeZeroMqEvent(TriggerSourceName, new Dictionary<string, object?> { { "source", "dotnet-console" } }, cancellationToken);
            //var configuredImage = runner.InvokeConfiguredZeroMqImage(TriggerSourceName, cancellationToken);
            //var imageFile = runner.InvokeZeroMqImageFromFile(TriggerSourceName, ImagePath, ImageMediaType, cancellationToken);
            var imageBytes = runner.InvokeZeroMqImageBytes(TriggerSourceName, LoadImageBytes(), ImageMediaType, cancellationToken);
            var imageBase64 = runner.InvokeZeroMqImageBase64(TriggerSourceName, LoadImageBase64(), ImageMediaType, cancellationToken);

            // ZeroMQ BGR24 raw 图片
            var frame = LoadBgr24ImageFrame();
            var bgr24 = runner.InvokeZeroMqBgr24(TriggerSourceName, frame.Bytes, frame.Width, frame.Height, cancellationToken);
            //var bgr24File = runner.InvokeZeroMqBgr24FromFile(TriggerSourceName, ImagePath, cancellationToken);
            //var configuredBgr24 = runner.InvokeConfiguredZeroMqBgr24Image(TriggerSourceName, cancellationToken);
            using (var bitmap = LoadBitmap())
            {
                var bgr24Bitmap = runner.InvokeZeroMqBgr24FromBitmap(TriggerSourceName, bitmap, cancellationToken);
            }

            await Task.CompletedTask.ConfigureAwait(false);
        }
    }
}
