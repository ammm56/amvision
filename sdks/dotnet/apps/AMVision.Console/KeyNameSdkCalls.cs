using Amvar.Vision;
using Newtonsoft.Json;
using System.IO;
using System.Threading;
using System.Threading.Tasks;
using static AMVision.Console.SdkCallInputs;

namespace AMVision.Console
{
    /// <summary>
    /// 使用 Config 中可读 name 的调用清单。按需取消具体调用行的注释。
    /// </summary>
    internal static class KeyNameSdkCalls
    {
        private const string ModelDeploymentName = "yolo11-s-pcbtrayslotsmall3570-20260804085356 model-build-ff706c3bede6";
        private const string RuntimeName = "摆盘分拣3570治具空盘检测应用";
        private const string ZeroMqTriggerSourceName = "摆盘分拣3570治具空盘检测应用 ZeroMQ Trigger";
        private const string SharedMemoryTriggerSourceName = "摆盘分拣3570治具空盘检测应用 Local Shared Memory Trigger";

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
            var status = await runner.CallAsync(api => api.GetModelDeploymentRuntimeStatusAsync(ModelDeploymentName, cancellationToken)).ConfigureAwait(false);
            var health = await runner.CallAsync(api => api.GetModelDeploymentRuntimeHealthAsync(ModelDeploymentName, cancellationToken)).ConfigureAwait(false);
            var start = await runner.CallAsync(api => api.StartModelDeploymentRuntimeAsync(ModelDeploymentName, cancellationToken)).ConfigureAwait(false);
            string resultStr = JsonConvert.SerializeObject(start, Formatting.Indented);
            var warmup = await runner.CallAsync(api => api.WarmupModelDeploymentRuntimeAsync(ModelDeploymentName, cancellationToken)).ConfigureAwait(false);
            //var reset = await runner.CallAsync(api => api.ResetModelDeploymentRuntimeAsync(ModelDeploymentName, cancellationToken)).ConfigureAwait(false);
            //var stop = await runner.CallAsync(api => api.StopModelDeploymentRuntimeAsync(ModelDeploymentName, cancellationToken)).ConfigureAwait(false);

            // 同步推理
            //var invoke = await runner.CallAsync(api => api.InvokeConfiguredModelDeploymentAsync(ModelDeploymentName, cancellationToken)).ConfigureAwait(false);
            var invokeBase64 = await runner.CallAsync(api => api.InvokeModelDeploymentWithImageBase64Async(ModelDeploymentName, LoadModelImageBase64(), cancellationToken)).ConfigureAwait(false);
            var invokeBytes = await runner.CallAsync(api => api.InvokeModelDeploymentWithImageBytesAsync(ModelDeploymentName, LoadModelImageBytes(), Path.GetFileName(ModelImagePath), ModelImageMediaType, cancellationToken)).ConfigureAwait(false);
            resultStr = JsonConvert.SerializeObject(invokeBytes, Formatting.Indented);
            //var invokeFile = await runner.CallAsync(api => api.InvokeModelDeploymentWithImageFromFileAsync(ModelDeploymentName, ModelImagePath, ModelImageMediaType, cancellationToken)).ConfigureAwait(false);
            //var invokeFileId = await runner.CallAsync(api => api.InvokeModelDeploymentWithInputFileIdAsync(ModelDeploymentName, ModelDeploymentInputFileId, cancellationToken)).ConfigureAwait(false);
            //var invokeUri = await runner.CallAsync(api => api.InvokeModelDeploymentWithInputUriAsync(ModelDeploymentName, ModelDeploymentInputUri, cancellationToken)).ConfigureAwait(false);

            // 异步推理任务
            //var run = await runner.CallAsync(api => api.RunConfiguredModelDeploymentAsync(ModelDeploymentName, cancellationToken)).ConfigureAwait(false);
            //var runBase64 = await runner.CallAsync(api => api.RunModelDeploymentWithImageBase64Async(ModelDeploymentName, LoadModelImageBase64(), cancellationToken)).ConfigureAwait(false);
            //var runBytes = await runner.CallAsync(api => api.RunModelDeploymentWithImageBytesAsync(ModelDeploymentName, LoadModelImageBytes(), Path.GetFileName(ModelImagePath), ModelImageMediaType, cancellationToken)).ConfigureAwait(false);
            //var runFile = await runner.CallAsync(api => api.RunModelDeploymentWithImageFromFileAsync(ModelDeploymentName, ModelImagePath, ModelImageMediaType, cancellationToken)).ConfigureAwait(false);
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
            var projectRuntimes = await runner.CallAsync(api => api.ListProjectRuntimesAsync(RuntimeName, cancellationToken)).ConfigureAwait(false);
            var runtime = await runner.CallAsync(api => api.GetRuntimeAsync(RuntimeName, cancellationToken)).ConfigureAwait(false);
            var health = await runner.CallAsync(api => api.GetRuntimeHealthAsync(RuntimeName, cancellationToken)).ConfigureAwait(false);
            var start = await runner.CallAsync(api => api.StartRuntimeAsync(RuntimeName, cancellationToken)).ConfigureAwait(false);
            string resultStr = JsonConvert.SerializeObject(start, Formatting.Indented);
            //var stop = await runner.CallAsync(api => api.StopRuntimeAsync(RuntimeName, cancellationToken)).ConfigureAwait(false);
            //var restart = await runner.CallAsync(api => api.RestartRuntimeAsync(RuntimeName, cancellationToken)).ConfigureAwait(false);
            //var instances = await runner.CallAsync(api => api.ListRuntimeInstancesAsync(RuntimeName, cancellationToken)).ConfigureAwait(false);
            //var events = await runner.CallAsync(api => api.GetRuntimeEventsAsync(RuntimeName, cancellationToken)).ConfigureAwait(false);
            //var flowCheck = await runner.CallAsync(api => api.CheckRuntimeFlowAsync(RuntimeName, cancellationToken)).ConfigureAwait(false);

            // 同步调用：默认输入或单图片
            //var invoke = await runner.CallAsync(api => api.InvokeRuntimeAppResultAsync(RuntimeName, cancellationToken)).ConfigureAwait(false);
            var invokeBase64 = await runner.CallAsync(api => api.InvokeRuntimeAppResultWithImageBase64Async(RuntimeName, LoadImageBase64(), ImageMediaType, cancellationToken)).ConfigureAwait(false);
            var invokeBytes = await runner.CallAsync(api => api.InvokeRuntimeAppResultWithImageBytesAsync(RuntimeName, LoadImageBytes(), ImageMediaType, cancellationToken)).ConfigureAwait(false);
            resultStr = JsonConvert.SerializeObject(invokeBytes, Formatting.Indented);
            //var invokeFile = await runner.CallAsync(api => api.InvokeRuntimeAppResultWithImageFromFileAsync(RuntimeName, ImagePath, ImageMediaType, cancellationToken)).ConfigureAwait(false);

            // 同步调用：按实际需要只提交本次使用的 optional binding
            var invokeImageBase64Inputs = await runner.CallAsync(api => api.InvokeRuntimeAppResultAsync(RuntimeName, CreateImageBase64RuntimeRequest(runner), cancellationToken)).ConfigureAwait(false);
            var invokeImageBase64JsonInputs = await runner.CallAsync(api => api.InvokeRuntimeAppResultAsync(RuntimeName, CreateImageBase64JsonRuntimeRequest(runner), cancellationToken)).ConfigureAwait(false);
            resultStr = JsonConvert.SerializeObject(invokeImageBase64JsonInputs, Formatting.Indented);

            // 全输入验证：使用 multipart 上传真实文件，不手工伪造 ObjectStore 引用
            var invokeAllMultipartInputs = await runner.CallAsync(api => api.InvokeRuntimeAppResultAsync(RuntimeName, CreateAllInputsMultipartRuntimeRequest(runner), cancellationToken)).ConfigureAwait(false);

            // 异步调用：默认输入或单图片
            //var run = await runner.CallAsync(api => api.RunRuntimeAsync(RuntimeName, cancellationToken)).ConfigureAwait(false);
            //var runBase64 = await runner.CallAsync(api => api.RunRuntimeWithImageBase64Async(RuntimeName, LoadImageBase64(), ImageMediaType, cancellationToken)).ConfigureAwait(false);
            //var runBytes = await runner.CallAsync(api => api.RunRuntimeWithImageBytesAsync(RuntimeName, LoadImageBytes(), ImageMediaType, cancellationToken)).ConfigureAwait(false);
            //var runFile = await runner.CallAsync(api => api.RunRuntimeWithImageFromFileAsync(RuntimeName, ImagePath, ImageMediaType, cancellationToken)).ConfigureAwait(false);

            // 异步调用：部分输入或全输入 multipart
            //var runImageBase64Inputs = await runner.CallAsync(api => api.RunRuntimeAsync(RuntimeName, CreateImageBase64RuntimeRequest(runner), cancellationToken)).ConfigureAwait(false);
            //var runImageBase64JsonInputs = await runner.CallAsync(api => api.RunRuntimeAsync(RuntimeName, CreateImageBase64JsonRuntimeRequest(runner), cancellationToken)).ConfigureAwait(false);
            //var runAllMultipartInputs = await runner.CallAsync(api => api.RunRuntimeAsync(RuntimeName, CreateAllInputsMultipartRuntimeRequest(runner), cancellationToken)).ConfigureAwait(false);

            // 异步任务查询与取消
            //var workflowRun = await runner.CallAsync(api => api.GetWorkflowRunAsync(WorkflowRunId, cancellationToken)).ConfigureAwait(false);
            //var runEvents = await runner.CallAsync(api => api.GetWorkflowRunEventsAsync(RuntimeName, WorkflowRunId, cancellationToken)).ConfigureAwait(false);
            //var cancel = await runner.CallAsync(api => api.CancelWorkflowRunAsync(WorkflowRunId, cancellationToken)).ConfigureAwait(false);

            await Task.CompletedTask.ConfigureAwait(false);
        }

        private static async Task RunTriggerSourceCallsAsync(
            AMVisionOperationRunner runner,
            CancellationToken cancellationToken)
        {
            // 管理与状态
            //var sources = await runner.CallAsync(api => api.ListTriggerSourcesAsync(RuntimeName, cancellationToken)).ConfigureAwait(false);
            //var source = await runner.CallAsync(api => api.GetTriggerSourceAsync(ZeroMqTriggerSourceName, cancellationToken)).ConfigureAwait(false);
            //var enable = await runner.CallAsync(api => api.EnableTriggerSourceAsync(ZeroMqTriggerSourceName, cancellationToken)).ConfigureAwait(false);
            //var disable = await runner.CallAsync(api => api.DisableTriggerSourceAsync(ZeroMqTriggerSourceName, cancellationToken)).ConfigureAwait(false);
            //var triggerHealth = await runner.CallAsync(api => api.GetTriggerSourceHealthAsync(ZeroMqTriggerSourceName, cancellationToken)).ConfigureAwait(false);

            // ZeroMQ：不带额外 JSON/Text
            //var zeroMqEvent = runner.Call(api => api.InvokeZeroMqEvent(ZeroMqTriggerSourceName, cancellationToken: cancellationToken));
            //var zeroMqConfiguredImage = runner.Call(api => api.InvokeConfiguredZeroMqImage(ZeroMqTriggerSourceName, cancellationToken));
            //var zeroMqImageFile = runner.Call(api => api.InvokeZeroMqImageFromFile(ZeroMqTriggerSourceName, ImagePath, ImageMediaType, cancellationToken));
            //var zeroMqImageBytes = runner.Call(api => api.InvokeZeroMqImageBytes(ZeroMqTriggerSourceName, LoadImageBytes(), ImageMediaType, cancellationToken));
            //var zeroMqImageBase64 = runner.Call(api => api.InvokeZeroMqImageBase64(ZeroMqTriggerSourceName, LoadImageBase64(), ImageMediaType, cancellationToken));
            //var zeroMqBgr24 = runner.Call(api => { var frame = LoadBgr24ImageFrame(); return api.InvokeZeroMqBgr24(ZeroMqTriggerSourceName, frame.Bytes, frame.Width, frame.Height, cancellationToken); });
            //var zeroMqBgr24File = runner.Call(api => api.InvokeZeroMqBgr24FromFile(ZeroMqTriggerSourceName, ImagePath, cancellationToken));
            //var zeroMqConfiguredBgr24 = runner.Call(api => api.InvokeConfiguredZeroMqBgr24Image(ZeroMqTriggerSourceName, cancellationToken));
            //var zeroMqBgr24Bitmap = runner.Call(api => { using (var bitmap = LoadBitmap()) return api.InvokeZeroMqBgr24FromBitmap(ZeroMqTriggerSourceName, bitmap, cancellationToken); });

            // ZeroMQ：image-ref + JSON + text
            //var zeroMqInputs = CreateTriggerInputs(runner, ZeroMqTriggerSourceName);
            //var zeroMqEventWithInputs = runner.Call(api => api.InvokeZeroMqEventWithInputs(ZeroMqTriggerSourceName, zeroMqInputs, cancellationToken));
            //var zeroMqConfiguredImageWithInputs = runner.Call(api => api.InvokeConfiguredZeroMqImageWithInputs(ZeroMqTriggerSourceName, zeroMqInputs, cancellationToken));
            //var zeroMqImageFileWithInputs = runner.Call(api => api.InvokeZeroMqImageFromFileWithInputs(ZeroMqTriggerSourceName, ImagePath, zeroMqInputs, ImageMediaType, cancellationToken));
            //var zeroMqImageBytesWithInputs = runner.Call(api => api.InvokeZeroMqImageBytesWithInputs(ZeroMqTriggerSourceName, LoadImageBytes(), zeroMqInputs, ImageMediaType, cancellationToken));
            //var zeroMqImageBase64WithInputs = runner.Call(api => api.InvokeZeroMqImageBase64WithInputs(ZeroMqTriggerSourceName, LoadImageBase64(), zeroMqInputs, ImageMediaType, cancellationToken));
            //var zeroMqBgr24WithInputs = runner.Call(api => { var frame = LoadBgr24ImageFrame(); return api.InvokeZeroMqBgr24WithInputs(ZeroMqTriggerSourceName, frame.Bytes, frame.Width, frame.Height, zeroMqInputs, cancellationToken); });
            //var zeroMqBgr24FileWithInputs = runner.Call(api => api.InvokeZeroMqBgr24FromFileWithInputs(ZeroMqTriggerSourceName, ImagePath, zeroMqInputs, cancellationToken));
            //var zeroMqConfiguredBgr24WithInputs = runner.Call(api => api.InvokeConfiguredZeroMqBgr24ImageWithInputs(ZeroMqTriggerSourceName, zeroMqInputs, cancellationToken));
            //var zeroMqBgr24BitmapWithInputs = runner.Call(api => { using (var bitmap = LoadBitmap()) return api.InvokeZeroMqBgr24FromBitmapWithInputs(ZeroMqTriggerSourceName, bitmap, zeroMqInputs, cancellationToken); });

            // Local Shared Memory：image-ref + JSON + text；使用后释放 Data
            //var sharedInputs = CreateTriggerInputs(runner, SharedMemoryTriggerSourceName);
            //var sharedEvent = runner.Call(api => api.InvokeSharedMemoryEventWithInputs(SharedMemoryTriggerSourceName, sharedInputs));
            //var sharedImageFile = runner.Call(api => api.InvokeSharedMemoryImageFromFileWithInputs(SharedMemoryTriggerSourceName, ImagePath, sharedInputs, ImageMediaType));
            //var sharedImageBytes = runner.Call(api => api.InvokeSharedMemoryImageBytesWithInputs(SharedMemoryTriggerSourceName, LoadImageBytes(), ImageMediaType, sharedInputs));
            //var sharedImageBase64 = runner.Call(api => api.InvokeSharedMemoryImageBase64WithInputs(SharedMemoryTriggerSourceName, LoadImageBase64(), sharedInputs, ImageMediaType));
            //var sharedBgr24 = runner.Call(api => { var frame = LoadBgr24ImageFrame(); return api.InvokeSharedMemoryBgr24WithInputs(SharedMemoryTriggerSourceName, frame.Bytes, frame.Width, frame.Height, sharedInputs); });
            //sharedEvent.Data?.Dispose();

            await Task.CompletedTask.ConfigureAwait(false);
        }

        private static WorkflowRuntimeInvokeRequest CreateImageBase64RuntimeRequest(
            AMVisionOperationRunner runner)
        {
            return runner.CreateWorkflowRequestBuilder(RuntimeName)
                .AddImageBase64("request_image_base64", LoadImageBytes(), ImageMediaType)
                .WithTimeoutSeconds(30)
                .BuildJson();
        }

        private static WorkflowRuntimeInvokeRequest CreateImageBase64JsonRuntimeRequest(
            AMVisionOperationRunner runner)
        {
            return runner.CreateWorkflowRequestBuilder(RuntimeName)
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
            return runner.CreateWorkflowRequestBuilder(RuntimeName)
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
            string triggerSourceName)
        {
            return runner.CreateWorkflowTriggerInputsBuilder(triggerSourceName)
                .AddJson("request_json", new { recipe = "3570", station = 2 })
                .AddText("request_text", "lot-20260831")
                .Build();
        }
    }
}
