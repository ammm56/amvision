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
        private const string ModelDeploymentName = "yolox-m-20260630190217 model-build-770c1fd9910e";
        private const string RuntimeName = "新建应用yoloxm条码识别";
        private const string TriggerSourceName = "ZeroMQ 图片触发 新建应用yoloxm条码识别 runtime";

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
            // 管理与状态；CallAsync 保留正常数据、后端错误响应或本地异常，不中断后续调用。
            var start = await runner.CallAsync(api => api.StartModelDeploymentRuntimeAsync(ModelDeploymentName, cancellationToken)).ConfigureAwait(false);
            var warmup = await runner.CallAsync(api => api.WarmupModelDeploymentRuntimeAsync(ModelDeploymentName, cancellationToken)).ConfigureAwait(false);
            //var reset = await runner.CallAsync(api => api.ResetModelDeploymentRuntimeAsync(ModelDeploymentName, cancellationToken)).ConfigureAwait(false);
            var stop = await runner.CallAsync(api => api.StopModelDeploymentRuntimeAsync(ModelDeploymentName, cancellationToken)).ConfigureAwait(false);
            var status = await runner.CallAsync(api => api.GetModelDeploymentRuntimeStatusAsync(ModelDeploymentName, cancellationToken)).ConfigureAwait(false);
            var health = await runner.CallAsync(api => api.GetModelDeploymentRuntimeHealthAsync(ModelDeploymentName, cancellationToken)).ConfigureAwait(false);

            // 同步推理
            //var invoke = await runner.CallAsync(api => api.InvokeConfiguredModelDeploymentAsync(ModelDeploymentName, cancellationToken)).ConfigureAwait(false);
            var invokeBase64 = await runner.CallAsync(api => api.InvokeModelDeploymentWithImageBase64Async(ModelDeploymentName, LoadImageBase64(), cancellationToken)).ConfigureAwait(false);
            var invokeBytes = await runner.CallAsync(api => api.InvokeModelDeploymentWithImageBytesAsync(ModelDeploymentName, LoadImageBytes(), Path.GetFileName(ImagePath), ImageMediaType, cancellationToken)).ConfigureAwait(false);
            //var invokeFile = await runner.CallAsync(api => api.InvokeModelDeploymentWithImageFromFileAsync(ModelDeploymentName, ImagePath, ImageMediaType, cancellationToken)).ConfigureAwait(false);
            //var invokeFileId = await runner.CallAsync(api => api.InvokeModelDeploymentWithInputFileIdAsync(ModelDeploymentName, ModelDeploymentInputFileId, cancellationToken)).ConfigureAwait(false);
            //var invokeUri = await runner.CallAsync(api => api.InvokeModelDeploymentWithInputUriAsync(ModelDeploymentName, ModelDeploymentInputUri, cancellationToken)).ConfigureAwait(false);

            // 异步推理任务
            //var run = await runner.CallAsync(api => api.RunConfiguredModelDeploymentAsync(ModelDeploymentName, cancellationToken)).ConfigureAwait(false);
            //var runBase64 = await runner.CallAsync(api => api.RunModelDeploymentWithImageBase64Async(ModelDeploymentName, LoadImageBase64(), cancellationToken)).ConfigureAwait(false);
            //var runBytes = await runner.CallAsync(api => api.RunModelDeploymentWithImageBytesAsync(ModelDeploymentName, LoadImageBytes(), Path.GetFileName(ImagePath), ImageMediaType, cancellationToken)).ConfigureAwait(false);
            //var runFile = await runner.CallAsync(api => api.RunModelDeploymentWithImageFromFileAsync(ModelDeploymentName, ImagePath, ImageMediaType, cancellationToken)).ConfigureAwait(false);
            //var runFileId = await runner.CallAsync(api => api.RunModelDeploymentWithInputFileIdAsync(ModelDeploymentName, ModelDeploymentInputFileId, cancellationToken)).ConfigureAwait(false);
            //var runUri = await runner.CallAsync(api => api.RunModelDeploymentWithInputUriAsync(ModelDeploymentName, ModelDeploymentInputUri, cancellationToken)).ConfigureAwait(false);
            //var task = await runner.CallAsync(api => api.GetModelInferenceTaskAsync(ModelDeploymentName, ModelInferenceTaskId, includeEvents: true, cancellationToken: cancellationToken)).ConfigureAwait(false);
            //var taskResult = await runner.CallAsync(api => api.GetModelInferenceTaskResultAsync(ModelDeploymentName, ModelInferenceTaskId, cancellationToken)).ConfigureAwait(false);

            await Task.CompletedTask.ConfigureAwait(false);
        }

        private static async Task RunWorkflowRuntimeCallsAsync(
            AMVisionOperationRunner runner,
            CancellationToken cancellationToken)
        {
            // 管理与状态
            //var projectRuntimes = await runner.CallAsync(api => api.ListProjectRuntimesAsync(RuntimeName, cancellationToken)).ConfigureAwait(false);
            var start = await runner.CallAsync(api => api.StartRuntimeAsync(RuntimeName, cancellationToken)).ConfigureAwait(false);
            var stop = await runner.CallAsync(api => api.StopRuntimeAsync(RuntimeName, cancellationToken)).ConfigureAwait(false);
            var runtime = await runner.CallAsync(api => api.GetRuntimeAsync(RuntimeName, cancellationToken)).ConfigureAwait(false);
            var health = await runner.CallAsync(api => api.GetRuntimeHealthAsync(RuntimeName, cancellationToken)).ConfigureAwait(false);
            //var restart = await runner.CallAsync(api => api.RestartRuntimeAsync(RuntimeName, cancellationToken)).ConfigureAwait(false);
            //var instances = await runner.CallAsync(api => api.ListRuntimeInstancesAsync(RuntimeName, cancellationToken)).ConfigureAwait(false);
            //var events = await runner.CallAsync(api => api.GetRuntimeEventsAsync(RuntimeName, cancellationToken)).ConfigureAwait(false);
            //var flowCheck = await runner.CallAsync(api => api.CheckRuntimeFlowAsync(RuntimeName, cancellationToken)).ConfigureAwait(false);

            // 同步调用
            //var invoke = await runner.CallAsync(api => api.InvokeRuntimeAppResultAsync(RuntimeName, cancellationToken)).ConfigureAwait(false);
            var invokeBase64 = await runner.CallAsync(api => api.InvokeRuntimeAppResultWithImageBase64Async(RuntimeName, LoadImageBase64(), ImageMediaType, cancellationToken)).ConfigureAwait(false);
            var invokeBytes = await runner.CallAsync(api => api.InvokeRuntimeAppResultWithImageBytesAsync(RuntimeName, LoadImageBytes(), ImageMediaType, cancellationToken)).ConfigureAwait(false);
            //var invokeFile = await runner.CallAsync(api => api.InvokeRuntimeAppResultWithImageFromFileAsync(RuntimeName, ImagePath, ImageMediaType, cancellationToken)).ConfigureAwait(false);

            // 异步任务
            //var run = await runner.CallAsync(api => api.RunRuntimeAsync(RuntimeName, cancellationToken)).ConfigureAwait(false);
            //var runBase64 = await runner.CallAsync(api => api.RunRuntimeWithImageBase64Async(RuntimeName, LoadImageBase64(), ImageMediaType, cancellationToken)).ConfigureAwait(false);
            //var runBytes = await runner.CallAsync(api => api.RunRuntimeWithImageBytesAsync(RuntimeName, LoadImageBytes(), ImageMediaType, cancellationToken)).ConfigureAwait(false);
            //var runFile = await runner.CallAsync(api => api.RunRuntimeWithImageFromFileAsync(RuntimeName, ImagePath, ImageMediaType, cancellationToken)).ConfigureAwait(false);
            //var workflowRun = await runner.CallAsync(api => api.GetWorkflowRunAsync(WorkflowRunId, cancellationToken)).ConfigureAwait(false);
            //var cancel = await runner.CallAsync(api => api.CancelWorkflowRunAsync(WorkflowRunId, cancellationToken)).ConfigureAwait(false);
            //var runEvents = await runner.CallAsync(api => api.GetWorkflowRunEventsAsync(RuntimeName, WorkflowRunId, cancellationToken)).ConfigureAwait(false);

            await Task.CompletedTask.ConfigureAwait(false);
        }

        private static async Task RunTriggerSourceCallsAsync(
            AMVisionOperationRunner runner,
            CancellationToken cancellationToken)
        {
            // 管理与状态
            //var sources = await runner.CallAsync(api => api.ListTriggerSourcesAsync(RuntimeName, cancellationToken)).ConfigureAwait(false);
            //var source = await runner.CallAsync(api => api.GetTriggerSourceAsync(TriggerSourceName, cancellationToken)).ConfigureAwait(false);
            var enable = await runner.CallAsync(api => api.EnableTriggerSourceAsync(TriggerSourceName, cancellationToken)).ConfigureAwait(false);
            var disable = await runner.CallAsync(api => api.DisableTriggerSourceAsync(TriggerSourceName, cancellationToken)).ConfigureAwait(false);
            var health = await runner.CallAsync(api => api.GetTriggerSourceHealthAsync(TriggerSourceName, cancellationToken)).ConfigureAwait(false);

            // ZeroMQ 事件与编码图片
            //var eventResult = runner.Call(api => api.InvokeZeroMqEvent(TriggerSourceName, new Dictionary<string, object?> { { "source", "dotnet-console" } }, cancellationToken));
            //var configuredImage = runner.Call(api => api.InvokeConfiguredZeroMqImage(TriggerSourceName, cancellationToken));
            //var imageFile = runner.Call(api => api.InvokeZeroMqImageFromFile(TriggerSourceName, ImagePath, ImageMediaType, cancellationToken));
            var imageBytes = runner.Call(api => api.InvokeZeroMqImageBytes(TriggerSourceName, LoadImageBytes(), ImageMediaType, cancellationToken));
            var imageBase64 = runner.Call(api => api.InvokeZeroMqImageBase64(TriggerSourceName, LoadImageBase64(), ImageMediaType, cancellationToken));

            // ZeroMQ BGR24 raw 图片
            var frame = LoadBgr24ImageFrame();
            var bgr24 = runner.Call(api => api.InvokeZeroMqBgr24(TriggerSourceName, frame.Bytes, frame.Width, frame.Height, cancellationToken));
            var bgr24File = runner.Call(api => api.InvokeZeroMqBgr24FromFile(TriggerSourceName, ImagePath, cancellationToken));
            //var configuredBgr24 = runner.Call(api => api.InvokeConfiguredZeroMqBgr24Image(TriggerSourceName, cancellationToken));
            using (var bitmap = LoadBitmap())
            {
                var bgr24Bitmap = runner.Call(api => api.InvokeZeroMqBgr24FromBitmap(TriggerSourceName, bitmap, cancellationToken));
            }

            await Task.CompletedTask.ConfigureAwait(false);
        }
    }
}
