using System.IO;
using System.Threading;
using System.Threading.Tasks;
using Amvar.Vision;
using Amvar.Vision.SharedMemory;
using static AMVision.Console.SdkCallInputs;

namespace AMVision.Console
{
    /// <summary>
    /// 使用 Config 中稳定 resource id 的调用清单。按需取消具体调用行的注释。
    /// </summary>
    internal static class ResourceIdSdkCalls
    {
        private const string ModelDeploymentId =
            "deployment-instance-bfd0e32dada14b509f023f700fb4c998";
        private const string RuntimeId =
            "workflow-runtime-9980d79a4d3744a0841ce07efaf19fc9";
        private const string ZeroMqTriggerSourceId =
            "zeromq-workflow-runtime-9980d79a4d3744a0841ce07efaf19fc9";
        private const string SharedMemoryTriggerSourceId =
            "local-shared-memory-workflow-runtime-9980d79a4d3744a0841ce07efaf19fc9";
        private const string SyncRuntimeMode = "sync";

        public static async Task RunAsync(
            AMVisionOperationRunner runner,
            CancellationToken cancellationToken)
        {
            // 各分类默认不发请求。只取消需要调试的调用行注释。
            await RunModelDeploymentCallsAsync(runner, cancellationToken).ConfigureAwait(false);
            await RunWorkflowRuntimeCallsAsync(runner, cancellationToken).ConfigureAwait(false);
            await RunTriggerSourceCallsAsync(runner, cancellationToken).ConfigureAwait(false);
        }

        private static async Task RunModelDeploymentCallsAsync(
            AMVisionOperationRunner runner,
            CancellationToken cancellationToken)
        {
            // 管理与状态
            //var status = await runner.CallAsync(api => api.GetModelDeploymentRuntimeStatusByIdAsync(ModelDeploymentId, SyncRuntimeMode, cancellationToken)).ConfigureAwait(false);
            //var health = await runner.CallAsync(api => api.GetModelDeploymentRuntimeHealthByIdAsync(ModelDeploymentId, SyncRuntimeMode, cancellationToken)).ConfigureAwait(false);
            //var start = await runner.CallAsync(api => api.StartModelDeploymentRuntimeByIdAsync(ModelDeploymentId, SyncRuntimeMode, cancellationToken)).ConfigureAwait(false);
            //var warmup = await runner.CallAsync(api => api.WarmupModelDeploymentRuntimeByIdAsync(ModelDeploymentId, SyncRuntimeMode, cancellationToken)).ConfigureAwait(false);
            //var reset = await runner.CallAsync(api => api.ResetModelDeploymentRuntimeByIdAsync(ModelDeploymentId, SyncRuntimeMode, cancellationToken)).ConfigureAwait(false);
            //var stop = await runner.CallAsync(api => api.StopModelDeploymentRuntimeByIdAsync(ModelDeploymentId, SyncRuntimeMode, cancellationToken)).ConfigureAwait(false);

            // 同步推理
            //var invoke = await runner.CallAsync(api => api.InvokeConfiguredModelDeploymentByIdAsync(ModelDeploymentId, cancellationToken)).ConfigureAwait(false);
            //var invokeBase64 = await runner.CallAsync(api => api.InvokeModelDeploymentWithImageBase64ByIdAsync(ModelDeploymentId, LoadModelImageBase64(), cancellationToken)).ConfigureAwait(false);
            //var invokeBytes = await runner.CallAsync(api => api.InvokeModelDeploymentWithImageBytesByIdAsync(ModelDeploymentId, LoadModelImageBytes(), Path.GetFileName(ModelImagePath), ModelImageMediaType, cancellationToken)).ConfigureAwait(false);
            //var invokeFile = await runner.CallAsync(api => api.InvokeModelDeploymentWithImageFromFileByIdAsync(ModelDeploymentId, ModelImagePath, ModelImageMediaType, cancellationToken)).ConfigureAwait(false);
            //var invokeFileId = await runner.CallAsync(api => api.InvokeModelDeploymentWithInputFileIdByIdAsync(ModelDeploymentId, ModelDeploymentInputFileId, cancellationToken)).ConfigureAwait(false);
            //var invokeUri = await runner.CallAsync(api => api.InvokeModelDeploymentWithInputUriByIdAsync(ModelDeploymentId, ModelDeploymentInputUri, cancellationToken)).ConfigureAwait(false);

            // 异步推理任务；需要 Config 中存在同一 deployment id 的 async 配置
            //var run = await runner.CallAsync(api => api.RunConfiguredModelDeploymentByIdAsync(ModelDeploymentId, cancellationToken)).ConfigureAwait(false);
            //var runBase64 = await runner.CallAsync(api => api.RunModelDeploymentWithImageBase64ByIdAsync(ModelDeploymentId, LoadModelImageBase64(), cancellationToken)).ConfigureAwait(false);
            //var runBytes = await runner.CallAsync(api => api.RunModelDeploymentWithImageBytesByIdAsync(ModelDeploymentId, LoadModelImageBytes(), Path.GetFileName(ModelImagePath), ModelImageMediaType, cancellationToken)).ConfigureAwait(false);
            //var runFile = await runner.CallAsync(api => api.RunModelDeploymentWithImageFromFileByIdAsync(ModelDeploymentId, ModelImagePath, ModelImageMediaType, cancellationToken)).ConfigureAwait(false);
            //var runFileId = await runner.CallAsync(api => api.RunModelDeploymentWithInputFileIdByIdAsync(ModelDeploymentId, ModelDeploymentInputFileId, cancellationToken)).ConfigureAwait(false);
            //var runUri = await runner.CallAsync(api => api.RunModelDeploymentWithInputUriByIdAsync(ModelDeploymentId, ModelDeploymentInputUri, cancellationToken)).ConfigureAwait(false);
            //var task = await runner.CallAsync(api => api.GetModelInferenceTaskByIdAsync(ModelDeploymentId, ModelInferenceTaskId, includeEvents: true, cancellationToken: cancellationToken)).ConfigureAwait(false);
            //var taskResult = await runner.CallAsync(api => api.GetModelInferenceTaskResultByIdAsync(ModelDeploymentId, ModelInferenceTaskId, cancellationToken)).ConfigureAwait(false);

            await Task.CompletedTask.ConfigureAwait(false);
        }

        private static async Task RunWorkflowRuntimeCallsAsync(
            AMVisionOperationRunner runner,
            CancellationToken cancellationToken)
        {
            // 管理与状态
            //var projectRuntimes = await runner.CallAsync(api => api.ListProjectRuntimesByIdAsync(RuntimeId, cancellationToken)).ConfigureAwait(false);
            //var runtime = await runner.CallAsync(api => api.GetRuntimeByIdAsync(RuntimeId, cancellationToken)).ConfigureAwait(false);
            //var health = await runner.CallAsync(api => api.GetRuntimeHealthByIdAsync(RuntimeId, cancellationToken)).ConfigureAwait(false);
            //var start = await runner.CallAsync(api => api.StartRuntimeByIdAsync(RuntimeId, cancellationToken)).ConfigureAwait(false);
            //var stop = await runner.CallAsync(api => api.StopRuntimeByIdAsync(RuntimeId, cancellationToken)).ConfigureAwait(false);
            //var restart = await runner.CallAsync(api => api.RestartRuntimeByIdAsync(RuntimeId, cancellationToken)).ConfigureAwait(false);
            //var instances = await runner.CallAsync(api => api.ListRuntimeInstancesByIdAsync(RuntimeId, cancellationToken)).ConfigureAwait(false);
            //var events = await runner.CallAsync(api => api.GetRuntimeEventsByIdAsync(RuntimeId, cancellationToken)).ConfigureAwait(false);
            //var flowCheck = await runner.CallAsync(api => api.CheckRuntimeFlowByIdAsync(RuntimeId, cancellationToken)).ConfigureAwait(false);

            // 同步调用：默认输入或单图片
            //var invoke = await runner.CallAsync(api => api.InvokeRuntimeAppResultByIdAsync(RuntimeId, cancellationToken)).ConfigureAwait(false);
            //var invokeBase64 = await runner.CallAsync(api => api.InvokeRuntimeAppResultWithImageBase64ByIdAsync(RuntimeId, LoadImageBase64(), ImageMediaType, cancellationToken)).ConfigureAwait(false);
            //var invokeBytes = await runner.CallAsync(api => api.InvokeRuntimeAppResultWithImageBytesByIdAsync(RuntimeId, LoadImageBytes(), ImageMediaType, cancellationToken)).ConfigureAwait(false);
            //var invokeFile = await runner.CallAsync(api => api.InvokeRuntimeAppResultWithImageFromFileByIdAsync(RuntimeId, ImagePath, ImageMediaType, cancellationToken)).ConfigureAwait(false);

            // 同步调用：按实际需要只提交本次使用的 optional binding
            //var invokeImageBase64Inputs = await runner.CallAsync(api => api.InvokeRuntimeAppResultByIdAsync(RuntimeId, CreateImageBase64RuntimeRequest(runner), cancellationToken)).ConfigureAwait(false);
            //var invokeImageBase64JsonInputs = await runner.CallAsync(api => api.InvokeRuntimeAppResultByIdAsync(RuntimeId, CreateImageBase64JsonRuntimeRequest(runner), cancellationToken)).ConfigureAwait(false);

            // 全输入验证：使用 multipart 上传真实文件，不手工伪造 ObjectStore 引用
            //var invokeAllMultipartInputs = await runner.CallAsync(api => api.InvokeRuntimeAppResultByIdAsync(RuntimeId, CreateAllInputsMultipartRuntimeRequest(runner), cancellationToken)).ConfigureAwait(false);

            // 异步调用：默认输入或单图片
            //var run = await runner.CallAsync(api => api.RunRuntimeByIdAsync(RuntimeId, cancellationToken)).ConfigureAwait(false);
            //var runBase64 = await runner.CallAsync(api => api.RunRuntimeWithImageBase64ByIdAsync(RuntimeId, LoadImageBase64(), ImageMediaType, cancellationToken)).ConfigureAwait(false);
            //var runBytes = await runner.CallAsync(api => api.RunRuntimeWithImageBytesByIdAsync(RuntimeId, LoadImageBytes(), ImageMediaType, cancellationToken)).ConfigureAwait(false);
            //var runFile = await runner.CallAsync(api => api.RunRuntimeWithImageFromFileByIdAsync(RuntimeId, ImagePath, ImageMediaType, cancellationToken)).ConfigureAwait(false);

            // 异步调用：部分输入或全输入 multipart
            //var runImageBase64Inputs = await runner.CallAsync(api => api.RunRuntimeByIdAsync(RuntimeId, CreateImageBase64RuntimeRequest(runner), cancellationToken)).ConfigureAwait(false);
            //var runImageBase64JsonInputs = await runner.CallAsync(api => api.RunRuntimeByIdAsync(RuntimeId, CreateImageBase64JsonRuntimeRequest(runner), cancellationToken)).ConfigureAwait(false);
            //var runAllMultipartInputs = await runner.CallAsync(api => api.RunRuntimeByIdAsync(RuntimeId, CreateAllInputsMultipartRuntimeRequest(runner), cancellationToken)).ConfigureAwait(false);

            // 异步任务查询与取消
            //var workflowRun = await runner.CallAsync(api => api.GetWorkflowRunAsync(WorkflowRunId, cancellationToken)).ConfigureAwait(false);
            //var runEvents = await runner.CallAsync(api => api.GetWorkflowRunEventsByRuntimeIdAsync(RuntimeId, WorkflowRunId, cancellationToken)).ConfigureAwait(false);
            //var cancel = await runner.CallAsync(api => api.CancelWorkflowRunAsync(WorkflowRunId, cancellationToken)).ConfigureAwait(false);

            await Task.CompletedTask.ConfigureAwait(false);
        }

        private static async Task RunTriggerSourceCallsAsync(
            AMVisionOperationRunner runner,
            CancellationToken cancellationToken)
        {
            // 管理与状态
            //var sources = await runner.CallAsync(api => api.ListTriggerSourcesByRuntimeIdAsync(RuntimeId, cancellationToken)).ConfigureAwait(false);
            //var source = await runner.CallAsync(api => api.GetTriggerSourceByIdAsync(ZeroMqTriggerSourceId, cancellationToken)).ConfigureAwait(false);
            //var enable = await runner.CallAsync(api => api.EnableTriggerSourceByIdAsync(ZeroMqTriggerSourceId, cancellationToken)).ConfigureAwait(false);
            //var disable = await runner.CallAsync(api => api.DisableTriggerSourceByIdAsync(ZeroMqTriggerSourceId, cancellationToken)).ConfigureAwait(false);
            //var triggerHealth = await runner.CallAsync(api => api.GetTriggerSourceHealthByIdAsync(ZeroMqTriggerSourceId, cancellationToken)).ConfigureAwait(false);

            // ZeroMQ：不带额外 JSON/Text
            //var zeroMqEvent = runner.Call(api => api.InvokeZeroMqEventById(ZeroMqTriggerSourceId, cancellationToken: cancellationToken));
            //var zeroMqConfiguredImage = runner.Call(api => api.InvokeConfiguredZeroMqImageById(ZeroMqTriggerSourceId, cancellationToken));
            //var zeroMqImageFile = runner.Call(api => api.InvokeZeroMqImageFromFileById(ZeroMqTriggerSourceId, ImagePath, ImageMediaType, cancellationToken));
            //var zeroMqImageBytes = runner.Call(api => api.InvokeZeroMqImageBytesById(ZeroMqTriggerSourceId, LoadImageBytes(), ImageMediaType, cancellationToken));
            //var zeroMqImageBase64 = runner.Call(api => api.InvokeZeroMqImageBase64ById(ZeroMqTriggerSourceId, LoadImageBase64(), ImageMediaType, cancellationToken));
            //var zeroMqBgr24 = runner.Call(api => { var frame = LoadBgr24ImageFrame(); return api.InvokeZeroMqBgr24ById(ZeroMqTriggerSourceId, frame.Bytes, frame.Width, frame.Height, cancellationToken); });
            //var zeroMqBgr24File = runner.Call(api => api.InvokeZeroMqBgr24FromFileById(ZeroMqTriggerSourceId, ImagePath, cancellationToken));
            //var zeroMqConfiguredBgr24 = runner.Call(api => api.InvokeConfiguredZeroMqBgr24ImageById(ZeroMqTriggerSourceId, cancellationToken));
            //var zeroMqBgr24Bitmap = runner.Call(api => { using (var bitmap = LoadBitmap()) return api.InvokeZeroMqBgr24FromBitmapById(ZeroMqTriggerSourceId, bitmap, cancellationToken); });

            // ZeroMQ：image-ref + JSON + text
            //var zeroMqInputs = CreateTriggerInputs(runner, ZeroMqTriggerSourceId);
            //var zeroMqEventWithInputs = runner.Call(api => api.InvokeZeroMqEventWithInputsById(ZeroMqTriggerSourceId, zeroMqInputs, cancellationToken));
            //var zeroMqConfiguredImageWithInputs = runner.Call(api => api.InvokeConfiguredZeroMqImageWithInputsById(ZeroMqTriggerSourceId, zeroMqInputs, cancellationToken));
            //var zeroMqImageFileWithInputs = runner.Call(api => api.InvokeZeroMqImageFromFileWithInputsById(ZeroMqTriggerSourceId, ImagePath, zeroMqInputs, ImageMediaType, cancellationToken));
            //var zeroMqImageBytesWithInputs = runner.Call(api => api.InvokeZeroMqImageBytesWithInputsById(ZeroMqTriggerSourceId, LoadImageBytes(), zeroMqInputs, ImageMediaType, cancellationToken));
            //var zeroMqImageBase64WithInputs = runner.Call(api => api.InvokeZeroMqImageBase64WithInputsById(ZeroMqTriggerSourceId, LoadImageBase64(), zeroMqInputs, ImageMediaType, cancellationToken));
            //var zeroMqBgr24WithInputs = runner.Call(api => { var frame = LoadBgr24ImageFrame(); return api.InvokeZeroMqBgr24WithInputsById(ZeroMqTriggerSourceId, frame.Bytes, frame.Width, frame.Height, zeroMqInputs, cancellationToken); });
            //var zeroMqBgr24FileWithInputs = runner.Call(api => api.InvokeZeroMqBgr24FromFileWithInputsById(ZeroMqTriggerSourceId, ImagePath, zeroMqInputs, cancellationToken));
            //var zeroMqConfiguredBgr24WithInputs = runner.Call(api => api.InvokeConfiguredZeroMqBgr24ImageWithInputsById(ZeroMqTriggerSourceId, zeroMqInputs, cancellationToken));
            //var zeroMqBgr24BitmapWithInputs = runner.Call(api => { using (var bitmap = LoadBitmap()) return api.InvokeZeroMqBgr24FromBitmapWithInputsById(ZeroMqTriggerSourceId, bitmap, zeroMqInputs, cancellationToken); });

            // Local Shared Memory：不带额外 JSON/Text；高层 API 返回统一 TriggerResult 并在返回前 ACK
            //var sharedEvent = runner.Call(api => api.InvokeSharedMemoryEventById(SharedMemoryTriggerSourceId, new SharedMemoryTriggerEventRequest()));
            //var sharedImageFile = runner.Call(api => api.InvokeSharedMemoryImageFromFileById(SharedMemoryTriggerSourceId, ImagePath, ImageMediaType));
            //var sharedImageBytes = runner.Call(api => api.InvokeSharedMemoryImageBytesById(SharedMemoryTriggerSourceId, LoadImageBytes(), ImageMediaType));
            //var sharedImageBase64 = runner.Call(api => api.InvokeSharedMemoryImageBase64ById(SharedMemoryTriggerSourceId, LoadImageBase64(), ImageMediaType));
            //var sharedBgr24 = runner.Call(api => { var frame = LoadBgr24ImageFrame(); return api.InvokeSharedMemoryBgr24ById(SharedMemoryTriggerSourceId, frame.Bytes, frame.Width, frame.Height); });
            // byte[] mono8Bytes = ...; int mono8Width = ...; int mono8Height = ...; int mono8RowStride = ...;
            //var sharedMono8 = runner.Call(api => api.InvokeSharedMemoryMono8ById(SharedMemoryTriggerSourceId, mono8Bytes, mono8Width, mono8Height, mono8RowStride));
            //var sharedBitmap = runner.Call(api => { using (var bitmap = LoadBitmap()) return api.InvokeSharedMemoryBitmapById(SharedMemoryTriggerSourceId, bitmap); });

            // Local Shared Memory：image-ref + JSON + text
            //var sharedInputs = CreateTriggerInputs(runner, SharedMemoryTriggerSourceId);
            //var sharedEvent = runner.Call(api => api.InvokeSharedMemoryEventWithInputsById(SharedMemoryTriggerSourceId, sharedInputs));
            //var sharedImageFile = runner.Call(api => api.InvokeSharedMemoryImageFromFileWithInputsById(SharedMemoryTriggerSourceId, ImagePath, sharedInputs, ImageMediaType));
            //var sharedImageBytes = runner.Call(api => api.InvokeSharedMemoryImageBytesWithInputsById(SharedMemoryTriggerSourceId, LoadImageBytes(), ImageMediaType, sharedInputs));
            //var sharedImageBase64 = runner.Call(api => api.InvokeSharedMemoryImageBase64WithInputsById(SharedMemoryTriggerSourceId, LoadImageBase64(), sharedInputs, ImageMediaType));
            //var sharedBgr24 = runner.Call(api => { var frame = LoadBgr24ImageFrame(); return api.InvokeSharedMemoryBgr24WithInputsById(SharedMemoryTriggerSourceId, frame.Bytes, frame.Width, frame.Height, sharedInputs); });
            await Task.CompletedTask.ConfigureAwait(false);
        }

        private static WorkflowRuntimeInvokeRequest CreateImageBase64RuntimeRequest(
            AMVisionOperationRunner runner)
        {
            return runner.CreateWorkflowRequestBuilderById(RuntimeId)
                .AddImageBase64("request_image_base64", LoadImageBytes(), ImageMediaType)
                .WithTimeoutSeconds(30)
                .BuildJson();
        }

        private static WorkflowRuntimeInvokeRequest CreateImageBase64JsonRuntimeRequest(
            AMVisionOperationRunner runner)
        {
            return runner.CreateWorkflowRequestBuilderById(RuntimeId)
                .AddImageBase64("request_image_base64", LoadImageBytes(), ImageMediaType)
                .AddJson("request_json", new
                {
                    recipe = "3570",
                    station = 2,
                    barqrcode = "abcdefg12345678"
                })
                .WithTimeoutSeconds(30)
                .BuildJson();
        }

        private static WorkflowRuntimeMultipartInvokeRequest CreateAllInputsMultipartRuntimeRequest(
            AMVisionOperationRunner runner)
        {
            return runner.CreateWorkflowRequestBuilderById(RuntimeId)
                .AddImage("request_image_ref", WorkflowUploadFile.FromFile(ImagePath, ImageMediaType))
                .AddImageBase64("request_image_base64", LoadImageBytes(), ImageMediaType)
                .AddJson("request_json", new { recipe = "3570", station = 2 })
                .AddText("request_text", "lot-20260831")
                .AddFile("request_file", CreateWorkflowRequestFile())
                .AddFiles("request_files", CreateWorkflowRequestFiles())
                .WithTimeoutSeconds(30)
                .BuildMultipart();
        }

        private static WorkflowTriggerInputs CreateTriggerInputs(
            AMVisionOperationRunner runner,
            string triggerSourceId)
        {
            return runner.CreateWorkflowTriggerInputsBuilderById(triggerSourceId)
                .AddJson("request_json", new { recipe = "3570", station = 2 })
                .AddText("request_text", "lot-20260831")
                .Build();
        }
    }
}
