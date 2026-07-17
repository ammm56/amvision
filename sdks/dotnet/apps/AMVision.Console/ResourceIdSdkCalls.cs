using System.Collections.Generic;
using System.IO;
using System.Threading;
using System.Threading.Tasks;
using Amvar.Vision;
using static AMVision.Console.SdkCallInputs;

namespace AMVision.Console
{
    /// <summary>
    /// 稳定兜底调用方式：显式使用 deployment_instance_id、workflow_runtime_id 和 trigger_source_id。
    /// 不把一个字符串同时解释为 name 或 id，示例顺序与 key name 文件保持一致。
    /// </summary>
    internal static class ResourceIdSdkCalls
    {
        private const string DeploymentInstanceId = "deployment-instance-8a186ddbab564e86a1649c16965ffa0f";
        private const string WorkflowRuntimeId = "workflow-runtime-768e3187953642e9a5a85353ffd96881";
        private const string TriggerSourceId = "zeromq-workflow-runtime-768e3187953642e9a5a85353ffd96881";
        private const string SyncRuntimeMode = "sync";

        public static async Task RunAsync(
            AMVisionOperationRunner runner,
            CancellationToken cancellationToken)
        {
            // 各分组内默认不发请求。按需取消具体调用行的注释。
            await RunModelDeploymentCallsAsync(runner, cancellationToken).ConfigureAwait(false);
            await RunWorkflowRuntimeCallsAsync(runner, cancellationToken).ConfigureAwait(false);
            await RunTriggerSourceCallsAsync(runner, cancellationToken).ConfigureAwait(false);
        }

        private static async Task RunModelDeploymentCallsAsync(
            AMVisionOperationRunner runner,
            CancellationToken cancellationToken)
        {
            // 管理与状态需要 runtime_mode，以明确区分同一 deployment id 的 sync/async 配置。
            //var status = await runner.CallAsync(api => api.GetModelDeploymentRuntimeStatusByIdAsync(DeploymentInstanceId, SyncRuntimeMode, cancellationToken)).ConfigureAwait(false);
            //var health = await runner.CallAsync(api => api.GetModelDeploymentRuntimeHealthByIdAsync(DeploymentInstanceId, SyncRuntimeMode, cancellationToken)).ConfigureAwait(false);
            //var start = await runner.CallAsync(api => api.StartModelDeploymentRuntimeByIdAsync(DeploymentInstanceId, SyncRuntimeMode, cancellationToken)).ConfigureAwait(false);
            //var warmup = await runner.CallAsync(api => api.WarmupModelDeploymentRuntimeByIdAsync(DeploymentInstanceId, SyncRuntimeMode, cancellationToken)).ConfigureAwait(false);
            //var reset = await runner.CallAsync(api => api.ResetModelDeploymentRuntimeByIdAsync(DeploymentInstanceId, SyncRuntimeMode, cancellationToken)).ConfigureAwait(false);
            //var stop = await runner.CallAsync(api => api.StopModelDeploymentRuntimeByIdAsync(DeploymentInstanceId, SyncRuntimeMode, cancellationToken)).ConfigureAwait(false);

            // 同步推理入口固定匹配 sync 配置。
            //var invoke = await runner.CallAsync(api => api.InvokeConfiguredModelDeploymentByIdAsync(DeploymentInstanceId, cancellationToken)).ConfigureAwait(false);
            //var invokeBase64 = await runner.CallAsync(api => api.InvokeModelDeploymentWithImageBase64ByIdAsync(DeploymentInstanceId, LoadImageBase64(), cancellationToken)).ConfigureAwait(false);
            //var invokeBytes = await runner.CallAsync(api => api.InvokeModelDeploymentWithImageBytesByIdAsync(DeploymentInstanceId, LoadImageBytes(), Path.GetFileName(ImagePath), ImageMediaType, cancellationToken)).ConfigureAwait(false);
            //var invokeFile = await runner.CallAsync(api => api.InvokeModelDeploymentWithImageFromFileByIdAsync(DeploymentInstanceId, ImagePath, ImageMediaType, cancellationToken)).ConfigureAwait(false);
            //var invokeFileId = await runner.CallAsync(api => api.InvokeModelDeploymentWithInputFileIdByIdAsync(DeploymentInstanceId, ModelDeploymentInputFileId, cancellationToken)).ConfigureAwait(false);
            //var invokeUri = await runner.CallAsync(api => api.InvokeModelDeploymentWithInputUriByIdAsync(DeploymentInstanceId, ModelDeploymentInputUri, cancellationToken)).ConfigureAwait(false);

            // 异步推理入口固定匹配 async 配置。
            //var run = await runner.CallAsync(api => api.RunConfiguredModelDeploymentByIdAsync(DeploymentInstanceId, cancellationToken)).ConfigureAwait(false);
            //var runBase64 = await runner.CallAsync(api => api.RunModelDeploymentWithImageBase64ByIdAsync(DeploymentInstanceId, LoadImageBase64(), cancellationToken)).ConfigureAwait(false);
            //var runBytes = await runner.CallAsync(api => api.RunModelDeploymentWithImageBytesByIdAsync(DeploymentInstanceId, LoadImageBytes(), Path.GetFileName(ImagePath), ImageMediaType, cancellationToken)).ConfigureAwait(false);
            //var runFile = await runner.CallAsync(api => api.RunModelDeploymentWithImageFromFileByIdAsync(DeploymentInstanceId, ImagePath, ImageMediaType, cancellationToken)).ConfigureAwait(false);
            //var runFileId = await runner.CallAsync(api => api.RunModelDeploymentWithInputFileIdByIdAsync(DeploymentInstanceId, ModelDeploymentInputFileId, cancellationToken)).ConfigureAwait(false);
            //var runUri = await runner.CallAsync(api => api.RunModelDeploymentWithInputUriByIdAsync(DeploymentInstanceId, ModelDeploymentInputUri, cancellationToken)).ConfigureAwait(false);
            //var task = await runner.CallAsync(api => api.GetModelInferenceTaskByIdAsync(DeploymentInstanceId, ModelInferenceTaskId, includeEvents: true, cancellationToken: cancellationToken)).ConfigureAwait(false);
            //var taskResult = await runner.CallAsync(api => api.GetModelInferenceTaskResultByIdAsync(DeploymentInstanceId, ModelInferenceTaskId, cancellationToken)).ConfigureAwait(false);

            await Task.CompletedTask.ConfigureAwait(false);
        }

        private static async Task RunWorkflowRuntimeCallsAsync(
            AMVisionOperationRunner runner,
            CancellationToken cancellationToken)
        {
            // 管理与状态
            //var projectRuntimes = await runner.CallAsync(api => api.ListProjectRuntimesByIdAsync(WorkflowRuntimeId, cancellationToken)).ConfigureAwait(false);
            //var runtime = await runner.CallAsync(api => api.GetRuntimeByIdAsync(WorkflowRuntimeId, cancellationToken)).ConfigureAwait(false);
            //var health = await runner.CallAsync(api => api.GetRuntimeHealthByIdAsync(WorkflowRuntimeId, cancellationToken)).ConfigureAwait(false);
            //var start = await runner.CallAsync(api => api.StartRuntimeByIdAsync(WorkflowRuntimeId, cancellationToken)).ConfigureAwait(false);
            //var stop = await runner.CallAsync(api => api.StopRuntimeByIdAsync(WorkflowRuntimeId, cancellationToken)).ConfigureAwait(false);
            //var restart = await runner.CallAsync(api => api.RestartRuntimeByIdAsync(WorkflowRuntimeId, cancellationToken)).ConfigureAwait(false);
            //var instances = await runner.CallAsync(api => api.ListRuntimeInstancesByIdAsync(WorkflowRuntimeId, cancellationToken)).ConfigureAwait(false);
            //var events = await runner.CallAsync(api => api.GetRuntimeEventsByIdAsync(WorkflowRuntimeId, cancellationToken)).ConfigureAwait(false);
            //var flowCheck = await runner.CallAsync(api => api.CheckRuntimeFlowByIdAsync(WorkflowRuntimeId, cancellationToken)).ConfigureAwait(false);

            // 同步调用
            //var invoke = await runner.CallAsync(api => api.InvokeRuntimeAppResultByIdAsync(WorkflowRuntimeId, cancellationToken)).ConfigureAwait(false);
            //var invokeBase64 = await runner.CallAsync(api => api.InvokeRuntimeAppResultWithImageBase64ByIdAsync(WorkflowRuntimeId, LoadImageBase64(), ImageMediaType, cancellationToken)).ConfigureAwait(false);
            //var invokeBytes = await runner.CallAsync(api => api.InvokeRuntimeAppResultWithImageBytesByIdAsync(WorkflowRuntimeId, LoadImageBytes(), ImageMediaType, cancellationToken)).ConfigureAwait(false);
            //var invokeFile = await runner.CallAsync(api => api.InvokeRuntimeAppResultWithImageFromFileByIdAsync(WorkflowRuntimeId, ImagePath, ImageMediaType, cancellationToken)).ConfigureAwait(false);

            // 异步任务
            //var run = await runner.CallAsync(api => api.RunRuntimeByIdAsync(WorkflowRuntimeId, cancellationToken)).ConfigureAwait(false);
            //var runBase64 = await runner.CallAsync(api => api.RunRuntimeWithImageBase64ByIdAsync(WorkflowRuntimeId, LoadImageBase64(), ImageMediaType, cancellationToken)).ConfigureAwait(false);
            //var runBytes = await runner.CallAsync(api => api.RunRuntimeWithImageBytesByIdAsync(WorkflowRuntimeId, LoadImageBytes(), ImageMediaType, cancellationToken)).ConfigureAwait(false);
            //var runFile = await runner.CallAsync(api => api.RunRuntimeWithImageFromFileByIdAsync(WorkflowRuntimeId, ImagePath, ImageMediaType, cancellationToken)).ConfigureAwait(false);
            //var runEvents = await runner.CallAsync(api => api.GetWorkflowRunEventsByRuntimeIdAsync(WorkflowRuntimeId, WorkflowRunId, cancellationToken)).ConfigureAwait(false);

            // WorkflowRun 自身已有唯一 id，以下接口不依赖 runtime selector。
            //var workflowRun = await runner.CallAsync(api => api.GetWorkflowRunAsync(WorkflowRunId, cancellationToken)).ConfigureAwait(false);
            //var cancel = await runner.CallAsync(api => api.CancelWorkflowRunAsync(WorkflowRunId, cancellationToken)).ConfigureAwait(false);

            await Task.CompletedTask.ConfigureAwait(false);
        }

        private static async Task RunTriggerSourceCallsAsync(
            AMVisionOperationRunner runner,
            CancellationToken cancellationToken)
        {
            // 列表按 workflow_runtime_id；单资源管理按 trigger_source_id。
            //var sources = await runner.CallAsync(api => api.ListTriggerSourcesByRuntimeIdAsync(WorkflowRuntimeId, cancellationToken)).ConfigureAwait(false);
            //var source = await runner.CallAsync(api => api.GetTriggerSourceByIdAsync(TriggerSourceId, cancellationToken)).ConfigureAwait(false);
            //var enable = await runner.CallAsync(api => api.EnableTriggerSourceByIdAsync(TriggerSourceId, cancellationToken)).ConfigureAwait(false);
            //var disable = await runner.CallAsync(api => api.DisableTriggerSourceByIdAsync(TriggerSourceId, cancellationToken)).ConfigureAwait(false);
            //var health = await runner.CallAsync(api => api.GetTriggerSourceHealthByIdAsync(TriggerSourceId, cancellationToken)).ConfigureAwait(false);

            // ZeroMQ 事件与编码图片
            //var eventResult = runner.Call(api => api.InvokeZeroMqEventById(TriggerSourceId, new Dictionary<string, object?> { { "source", "dotnet-console" } }, cancellationToken));
            //var configuredImage = runner.Call(api => api.InvokeConfiguredZeroMqImageById(TriggerSourceId, cancellationToken));
            //var imageFile = runner.Call(api => api.InvokeZeroMqImageFromFileById(TriggerSourceId, ImagePath, ImageMediaType, cancellationToken));
            //var imageBytes = runner.Call(api => api.InvokeZeroMqImageBytesById(TriggerSourceId, LoadImageBytes(), ImageMediaType, cancellationToken));
            //var imageBase64 = runner.Call(api => api.InvokeZeroMqImageBase64ById(TriggerSourceId, LoadImageBase64(), ImageMediaType, cancellationToken));

            // ZeroMQ BGR24 raw 图片
            //var frame = LoadBgr24ImageFrame();
            //var bgr24 = runner.Call(api => api.InvokeZeroMqBgr24ById(TriggerSourceId, frame.Bytes, frame.Width, frame.Height, cancellationToken));
            //var bgr24File = runner.Call(api => api.InvokeZeroMqBgr24FromFileById(TriggerSourceId, ImagePath, cancellationToken));
            //var configuredBgr24 = runner.Call(api => api.InvokeConfiguredZeroMqBgr24ImageById(TriggerSourceId, cancellationToken));
            //using (var bitmap = LoadBitmap())
            //{
            //    var bgr24Bitmap = runner.Call(api => api.InvokeZeroMqBgr24FromBitmapById(TriggerSourceId, bitmap, cancellationToken));
            //}

            await Task.CompletedTask.ConfigureAwait(false);
        }
    }
}
