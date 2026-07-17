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
            //var status = await runner.GetModelDeploymentRuntimeStatusByIdAsync(DeploymentInstanceId, SyncRuntimeMode, cancellationToken).ConfigureAwait(false);
            //var health = await runner.GetModelDeploymentRuntimeHealthByIdAsync(DeploymentInstanceId, SyncRuntimeMode, cancellationToken).ConfigureAwait(false);
            //var start = await runner.StartModelDeploymentRuntimeByIdAsync(DeploymentInstanceId, SyncRuntimeMode, cancellationToken).ConfigureAwait(false);
            //var warmup = await runner.WarmupModelDeploymentRuntimeByIdAsync(DeploymentInstanceId, SyncRuntimeMode, cancellationToken).ConfigureAwait(false);
            //var reset = await runner.ResetModelDeploymentRuntimeByIdAsync(DeploymentInstanceId, SyncRuntimeMode, cancellationToken).ConfigureAwait(false);
            //var stop = await runner.StopModelDeploymentRuntimeByIdAsync(DeploymentInstanceId, SyncRuntimeMode, cancellationToken).ConfigureAwait(false);

            // 同步推理入口固定匹配 sync 配置。
            //var invoke = await runner.InvokeConfiguredModelDeploymentByIdAsync(DeploymentInstanceId, cancellationToken).ConfigureAwait(false);
            //var invokeBase64 = await runner.InvokeModelDeploymentWithImageBase64ByIdAsync(DeploymentInstanceId, LoadImageBase64(), cancellationToken).ConfigureAwait(false);
            //var invokeBytes = await runner.InvokeModelDeploymentWithImageBytesByIdAsync(DeploymentInstanceId, LoadImageBytes(), Path.GetFileName(ImagePath), ImageMediaType, cancellationToken).ConfigureAwait(false);
            //var invokeFile = await runner.InvokeModelDeploymentWithImageFromFileByIdAsync(DeploymentInstanceId, ImagePath, ImageMediaType, cancellationToken).ConfigureAwait(false);
            //var invokeFileId = await runner.InvokeModelDeploymentWithInputFileIdByIdAsync(DeploymentInstanceId, ModelDeploymentInputFileId, cancellationToken).ConfigureAwait(false);
            //var invokeUri = await runner.InvokeModelDeploymentWithInputUriByIdAsync(DeploymentInstanceId, ModelDeploymentInputUri, cancellationToken).ConfigureAwait(false);

            // 异步推理入口固定匹配 async 配置。
            //var run = await runner.RunConfiguredModelDeploymentByIdAsync(DeploymentInstanceId, cancellationToken).ConfigureAwait(false);
            //var runBase64 = await runner.RunModelDeploymentWithImageBase64ByIdAsync(DeploymentInstanceId, LoadImageBase64(), cancellationToken).ConfigureAwait(false);
            //var runBytes = await runner.RunModelDeploymentWithImageBytesByIdAsync(DeploymentInstanceId, LoadImageBytes(), Path.GetFileName(ImagePath), ImageMediaType, cancellationToken).ConfigureAwait(false);
            //var runFile = await runner.RunModelDeploymentWithImageFromFileByIdAsync(DeploymentInstanceId, ImagePath, ImageMediaType, cancellationToken).ConfigureAwait(false);
            //var runFileId = await runner.RunModelDeploymentWithInputFileIdByIdAsync(DeploymentInstanceId, ModelDeploymentInputFileId, cancellationToken).ConfigureAwait(false);
            //var runUri = await runner.RunModelDeploymentWithInputUriByIdAsync(DeploymentInstanceId, ModelDeploymentInputUri, cancellationToken).ConfigureAwait(false);
            //var task = await runner.GetModelInferenceTaskByIdAsync(DeploymentInstanceId, ModelInferenceTaskId, includeEvents: true, cancellationToken: cancellationToken).ConfigureAwait(false);
            //var taskResult = await runner.GetModelInferenceTaskResultByIdAsync(DeploymentInstanceId, ModelInferenceTaskId, cancellationToken).ConfigureAwait(false);

            await Task.CompletedTask.ConfigureAwait(false);
        }

        private static async Task RunWorkflowRuntimeCallsAsync(
            AMVisionOperationRunner runner,
            CancellationToken cancellationToken)
        {
            // 管理与状态
            //var projectRuntimes = await runner.ListProjectRuntimesByIdAsync(WorkflowRuntimeId, cancellationToken).ConfigureAwait(false);
            //var runtime = await runner.GetRuntimeByIdAsync(WorkflowRuntimeId, cancellationToken).ConfigureAwait(false);
            //var health = await runner.GetRuntimeHealthByIdAsync(WorkflowRuntimeId, cancellationToken).ConfigureAwait(false);
            //var start = await runner.StartRuntimeByIdAsync(WorkflowRuntimeId, cancellationToken).ConfigureAwait(false);
            //var stop = await runner.StopRuntimeByIdAsync(WorkflowRuntimeId, cancellationToken).ConfigureAwait(false);
            //var restart = await runner.RestartRuntimeByIdAsync(WorkflowRuntimeId, cancellationToken).ConfigureAwait(false);
            //var instances = await runner.ListRuntimeInstancesByIdAsync(WorkflowRuntimeId, cancellationToken).ConfigureAwait(false);
            //var events = await runner.GetRuntimeEventsByIdAsync(WorkflowRuntimeId, cancellationToken).ConfigureAwait(false);
            //var flowCheck = await runner.CheckRuntimeFlowByIdAsync(WorkflowRuntimeId, cancellationToken).ConfigureAwait(false);

            // 同步调用
            //var invoke = await runner.InvokeRuntimeAppResultByIdAsync(WorkflowRuntimeId, cancellationToken).ConfigureAwait(false);
            //var invokeBase64 = await runner.InvokeRuntimeAppResultWithImageBase64ByIdAsync(WorkflowRuntimeId, LoadImageBase64(), ImageMediaType, cancellationToken).ConfigureAwait(false);
            //var invokeBytes = await runner.InvokeRuntimeAppResultWithImageBytesByIdAsync(WorkflowRuntimeId, LoadImageBytes(), ImageMediaType, cancellationToken).ConfigureAwait(false);
            //var invokeFile = await runner.InvokeRuntimeAppResultWithImageFromFileByIdAsync(WorkflowRuntimeId, ImagePath, ImageMediaType, cancellationToken).ConfigureAwait(false);

            // 异步任务
            //var run = await runner.RunRuntimeByIdAsync(WorkflowRuntimeId, cancellationToken).ConfigureAwait(false);
            //var runBase64 = await runner.RunRuntimeWithImageBase64ByIdAsync(WorkflowRuntimeId, LoadImageBase64(), ImageMediaType, cancellationToken).ConfigureAwait(false);
            //var runBytes = await runner.RunRuntimeWithImageBytesByIdAsync(WorkflowRuntimeId, LoadImageBytes(), ImageMediaType, cancellationToken).ConfigureAwait(false);
            //var runFile = await runner.RunRuntimeWithImageFromFileByIdAsync(WorkflowRuntimeId, ImagePath, ImageMediaType, cancellationToken).ConfigureAwait(false);
            //var runEvents = await runner.GetWorkflowRunEventsByRuntimeIdAsync(WorkflowRuntimeId, WorkflowRunId, cancellationToken).ConfigureAwait(false);

            // WorkflowRun 自身已有唯一 id，以下接口不依赖 runtime selector。
            //var workflowRun = await runner.GetWorkflowRunAsync(WorkflowRunId, cancellationToken).ConfigureAwait(false);
            //var cancel = await runner.CancelWorkflowRunAsync(WorkflowRunId, cancellationToken).ConfigureAwait(false);

            await Task.CompletedTask.ConfigureAwait(false);
        }

        private static async Task RunTriggerSourceCallsAsync(
            AMVisionOperationRunner runner,
            CancellationToken cancellationToken)
        {
            // 列表按 workflow_runtime_id；单资源管理按 trigger_source_id。
            //var sources = await runner.ListTriggerSourcesByRuntimeIdAsync(WorkflowRuntimeId, cancellationToken).ConfigureAwait(false);
            //var source = await runner.GetTriggerSourceByIdAsync(TriggerSourceId, cancellationToken).ConfigureAwait(false);
            //var enable = await runner.EnableTriggerSourceByIdAsync(TriggerSourceId, cancellationToken).ConfigureAwait(false);
            //var disable = await runner.DisableTriggerSourceByIdAsync(TriggerSourceId, cancellationToken).ConfigureAwait(false);
            //var health = await runner.GetTriggerSourceHealthByIdAsync(TriggerSourceId, cancellationToken).ConfigureAwait(false);

            // ZeroMQ 事件与编码图片
            //var eventResult = runner.InvokeZeroMqEventById(TriggerSourceId, new Dictionary<string, object?> { { "source", "dotnet-console" } }, cancellationToken);
            //var configuredImage = runner.InvokeConfiguredZeroMqImageById(TriggerSourceId, cancellationToken);
            //var imageFile = runner.InvokeZeroMqImageFromFileById(TriggerSourceId, ImagePath, ImageMediaType, cancellationToken);
            //var imageBytes = runner.InvokeZeroMqImageBytesById(TriggerSourceId, LoadImageBytes(), ImageMediaType, cancellationToken);
            //var imageBase64 = runner.InvokeZeroMqImageBase64ById(TriggerSourceId, LoadImageBase64(), ImageMediaType, cancellationToken);

            // ZeroMQ BGR24 raw 图片
            //var frame = LoadBgr24ImageFrame();
            //var bgr24 = runner.InvokeZeroMqBgr24ById(TriggerSourceId, frame.Bytes, frame.Width, frame.Height, cancellationToken);
            //var bgr24File = runner.InvokeZeroMqBgr24FromFileById(TriggerSourceId, ImagePath, cancellationToken);
            //var configuredBgr24 = runner.InvokeConfiguredZeroMqBgr24ImageById(TriggerSourceId, cancellationToken);
            //using (var bitmap = LoadBitmap())
            //{
            //    var bgr24Bitmap = runner.InvokeZeroMqBgr24FromBitmapById(TriggerSourceId, bitmap, cancellationToken);
            //}

            await Task.CompletedTask.ConfigureAwait(false);
        }
    }
}
