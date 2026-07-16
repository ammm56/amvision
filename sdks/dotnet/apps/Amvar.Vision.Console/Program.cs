using System;
using System.Collections.Generic;
using System.Drawing;
using System.IO;
using System.Threading;
using System.Threading.Tasks;
using Amvar.Vision;
using Amvar.Vision.Tools;
using Newtonsoft.Json;

namespace Amvar.Vision.ConsoleApp
{
    /// <summary>
    /// 控制台程序入口，用于调试和演示 Amvar.Vision SDK 的完整调用方式。
    /// </summary>
    internal static class Program
    {
        /// <summary>
        /// 是否执行 Workflow runtime 相关样例。
        /// </summary>
        private static readonly bool RunWorkflowRuntimeExamples = false;

        /// <summary>
        /// 是否执行 Workflow runtime 启停类样例。
        /// </summary>
        private static readonly bool RunWorkflowRuntimeMutationExamples = false;

        /// <summary>
        /// 是否执行 Model deployment 相关样例。
        /// </summary>
        private static readonly bool RunModelDeploymentExamples = false;

        /// <summary>
        /// 是否执行 Model deployment 启停类样例。
        /// </summary>
        private static readonly bool RunModelDeploymentMutationExamples = false;

        /// <summary>
        /// 是否执行 TriggerSource 管理相关样例。
        /// </summary>
        private static readonly bool RunTriggerSourceExamples = false;

        /// <summary>
        /// 是否执行 TriggerSource 启停类样例。
        /// </summary>
        private static readonly bool RunTriggerSourceMutationExamples = false;

        /// <summary>
        /// 是否执行 ZeroMQ 触发相关样例。
        /// </summary>
        private static readonly bool RunZeroMqTriggerExamples = false;

        /// <summary>
        /// 是否执行图片转换工具样例。
        /// </summary>
        private static readonly bool RunImageConversionExamples = false;

        /// <summary>
        /// Workflow runtime 配置 key，对应 Config/config*.json 中 runtimes[].name。
        /// </summary>
        private const string RuntimeName = "yolo11m_barqrcode";

        /// <summary>
        /// ZeroMQ TriggerSource 配置 key，对应 Config/config*.json 中 trigger_sources[].name。
        /// </summary>
        private const string TriggerSourceName = "zeromq_yolo11m_barqrcode";

        /// <summary>
        /// Model deployment 配置 key，对应 Config/config*.json 中 model_deployments[].name。
        /// </summary>
        private const string ModelDeploymentName = "yolo11_m_20260630190724_sync_2";

        /// <summary>
        /// 调试图片路径；相对路径会按控制台当前工作目录解析。
        /// </summary>
        private const string ImagePath = @"Resources\Img\qrcode50.jpg";

        /// <summary>
        /// 示例 WorkflowRun id；调试时替换为真实后端返回值。
        /// </summary>
        private const string WorkflowRunId = "workflow-run-id";

        /// <summary>
        /// 示例异步推理任务 id；调试时替换为真实后端返回值。
        /// </summary>
        private const string InferenceTaskId = "inference-task-id";

        /// <summary>
        /// 示例后端文件 id；调试时替换为真实文件 id。
        /// </summary>
        private const string InputFileId = "input-file-id";

        /// <summary>
        /// 示例后端可读取的 input_uri；调试时替换为真实 URI。
        /// </summary>
        private const string InputUri = "memory://runtime/inputs/inference/input.jpg";

        /// <summary>
        /// 默认图片 media type。
        /// </summary>
        private const string ImageMediaType = "image/jpeg";

        /// <summary>
        /// 程序入口。异常输出保持英文，避免 Windows 控制台编码差异导致乱码。
        /// </summary>
        /// <returns>进程退出码；0 表示成功。</returns>
        private static int Main()
        {
            try
            {
                MainAsync(CancellationToken.None).GetAwaiter().GetResult();
                return 0;
            }
            catch (AMVisionApiException exception)
            {
                WriteApiException(exception);
                return 2;
            }
            catch (AMVisionTransportException exception)
            {
                WriteKnownException("HTTP transport failed", exception);
                return 3;
            }
            catch (AMVisionTriggerException exception)
            {
                WriteTriggerException(exception);
                return 4;
            }
            catch (ArgumentException exception)
            {
                WriteKnownException("Invalid argument", exception);
                return 5;
            }
            catch (InvalidOperationException exception)
            {
                WriteKnownException("Invalid operation", exception);
                return 6;
            }
            catch (IOException exception)
            {
                WriteKnownException("File IO failed", exception);
                return 7;
            }
            catch (Exception exception)
            {
                System.Console.Error.WriteLine("Unhandled exception:");
                System.Console.Error.WriteLine(exception);
                return 1;
            }
            finally
            {
                WaitForKeyIfInteractive();
            }
        }

        /// <summary>
        /// 执行控制台调试调用。默认只执行系统配置检查，其余调用通过顶部开关启用。
        /// </summary>
        /// <param name="cancellationToken">取消信号。</param>
        private static async Task MainAsync(CancellationToken cancellationToken)
        {
            using (var runner = AMVisionOperationRunner.CreateDefault())
            {
                PrintLoadedConfigurations(runner);

                var systemConfig = await runner.GetSystemConfigResponseAsync(cancellationToken).ConfigureAwait(false);
                PrintHealthSummary(systemConfig);

                if (RunWorkflowRuntimeExamples)
                {
                    await RunWorkflowRuntimeExamplesAsync(runner, cancellationToken).ConfigureAwait(false);
                }

                if (RunWorkflowRuntimeMutationExamples)
                {
                    await RunWorkflowRuntimeMutationExamplesAsync(runner, cancellationToken).ConfigureAwait(false);
                }

                if (RunModelDeploymentExamples)
                {
                    await RunModelDeploymentExamplesAsync(runner, cancellationToken).ConfigureAwait(false);
                }

                if (RunModelDeploymentMutationExamples)
                {
                    await RunModelDeploymentMutationExamplesAsync(runner, cancellationToken).ConfigureAwait(false);
                }

                if (RunTriggerSourceExamples)
                {
                    await RunTriggerSourceExamplesAsync(runner, cancellationToken).ConfigureAwait(false);
                }

                if (RunTriggerSourceMutationExamples)
                {
                    await RunTriggerSourceMutationExamplesAsync(runner, cancellationToken).ConfigureAwait(false);
                }

                if (RunZeroMqTriggerExamples)
                {
                    await RunZeroMqTriggerExamplesAsync(runner, cancellationToken).ConfigureAwait(false);
                }

                if (RunImageConversionExamples)
                {
                    RunImageConversionToolExamples();
                }
            }
        }

        /// <summary>
        /// 输出已加载配置 key，确认 SDK 已自动加载 Config/config*.json。
        /// </summary>
        /// <param name="runner">SDK 高层操作入口。</param>
        private static void PrintLoadedConfigurations(AMVisionOperationRunner runner)
        {
            PrintSection("Loaded configuration keys");
            System.Console.WriteLine("Runtimes: " + JoinNames(runner.RuntimeNames));
            System.Console.WriteLine("TriggerSources: " + JoinNames(runner.TriggerSourceNames));
            System.Console.WriteLine("ModelDeployments: " + JoinNames(runner.ModelDeploymentNames));
        }

        /// <summary>
        /// 执行 Workflow runtime 只读和调用类样例。
        /// </summary>
        /// <param name="runner">SDK 高层操作入口。</param>
        /// <param name="cancellationToken">取消信号。</param>
        private static async Task RunWorkflowRuntimeExamplesAsync(
            AMVisionOperationRunner runner,
            CancellationToken cancellationToken)
        {
            PrintSection("Workflow runtime list");
            var runtimes = await runner.ListProjectRuntimesAsync(RuntimeName, cancellationToken).ConfigureAwait(false);
            PrintJson(runtimes);

            PrintSection("Workflow runtime status");
            var runtime = await runner.GetRuntimeAsync(RuntimeName, cancellationToken).ConfigureAwait(false);
            PrintJson(runtime);

            PrintSection("Workflow runtime health");
            var health = await runner.GetRuntimeHealthAsync(RuntimeName, cancellationToken).ConfigureAwait(false);
            PrintJson(health);

            PrintSection("Workflow runtime instances");
            var instances = await runner.ListRuntimeInstancesAsync(RuntimeName, cancellationToken).ConfigureAwait(false);
            PrintJson(instances);

            PrintSection("Workflow runtime events");
            var runtimeEvents = await runner.GetRuntimeEventsAsync(RuntimeName, cancellationToken).ConfigureAwait(false);
            PrintJson(runtimeEvents);

            PrintSection("Workflow runtime flow check");
            var flowCheck = await runner.CheckRuntimeFlowAsync(RuntimeName, cancellationToken).ConfigureAwait(false);
            PrintJson(flowCheck);

            PrintSection("Workflow runtime invoke with configured input");
            var configuredInvoke = await runner.InvokeRuntimeAppResultAsync(RuntimeName, cancellationToken).ConfigureAwait(false);
            PrintJson(configuredInvoke);

            PrintSection("Workflow runtime invoke with image file");
            var fileInvoke = await runner.InvokeRuntimeAppResultWithImageFromFileAsync(
                RuntimeName,
                ResolveImagePath(ImagePath),
                ImageMediaType,
                cancellationToken).ConfigureAwait(false);
            PrintJson(fileInvoke);

            PrintSection("Workflow runtime invoke with image bytes");
            var imageBytes = ReadImageBytes(ImagePath);
            var bytesInvoke = await runner.InvokeRuntimeAppResultWithImageBytesAsync(
                RuntimeName,
                imageBytes,
                ImageMediaType,
                cancellationToken).ConfigureAwait(false);
            PrintJson(bytesInvoke);

            PrintSection("Workflow runtime invoke with image base64");
            var imageBase64 = Convert.ToBase64String(imageBytes);
            var base64Invoke = await runner.InvokeRuntimeAppResultWithImageBase64Async(
                RuntimeName,
                imageBase64,
                ImageMediaType,
                cancellationToken).ConfigureAwait(false);
            PrintJson(base64Invoke);

            PrintSection("Workflow runtime async run with configured input");
            var configuredRun = await runner.RunRuntimeAsync(RuntimeName, cancellationToken).ConfigureAwait(false);
            PrintJson(configuredRun);

            PrintSection("Workflow runtime async run with image file");
            var fileRun = await runner.RunRuntimeWithImageFromFileAsync(
                RuntimeName,
                ResolveImagePath(ImagePath),
                ImageMediaType,
                cancellationToken).ConfigureAwait(false);
            PrintJson(fileRun);

            PrintSection("Workflow runtime async run with image bytes");
            var bytesRun = await runner.RunRuntimeWithImageBytesAsync(
                RuntimeName,
                imageBytes,
                ImageMediaType,
                cancellationToken).ConfigureAwait(false);
            PrintJson(bytesRun);

            PrintSection("Workflow runtime async run with image base64");
            var base64Run = await runner.RunRuntimeWithImageBase64Async(
                RuntimeName,
                imageBase64,
                ImageMediaType,
                cancellationToken).ConfigureAwait(false);
            PrintJson(base64Run);

            PrintSection("Workflow run detail");
            var workflowRun = await runner.GetWorkflowRunAsync(WorkflowRunId, cancellationToken).ConfigureAwait(false);
            PrintJson(workflowRun);

            PrintSection("Workflow run events");
            var workflowRunEvents = await runner.GetWorkflowRunEventsAsync(
                RuntimeName,
                WorkflowRunId,
                cancellationToken).ConfigureAwait(false);
            PrintJson(workflowRunEvents);
        }

        /// <summary>
        /// 执行 Workflow runtime 启停类样例。
        /// </summary>
        /// <param name="runner">SDK 高层操作入口。</param>
        /// <param name="cancellationToken">取消信号。</param>
        private static async Task RunWorkflowRuntimeMutationExamplesAsync(
            AMVisionOperationRunner runner,
            CancellationToken cancellationToken)
        {
            PrintSection("Workflow runtime start");
            var started = await runner.StartRuntimeAsync(RuntimeName, cancellationToken).ConfigureAwait(false);
            PrintJson(started);

            PrintSection("Workflow runtime restart");
            var restarted = await runner.RestartRuntimeAsync(RuntimeName, cancellationToken).ConfigureAwait(false);
            PrintJson(restarted);

            PrintSection("Workflow run cancel");
            var canceledRun = await runner.CancelWorkflowRunAsync(WorkflowRunId, cancellationToken).ConfigureAwait(false);
            PrintJson(canceledRun);

            PrintSection("Workflow runtime stop");
            var stopped = await runner.StopRuntimeAsync(RuntimeName, cancellationToken).ConfigureAwait(false);
            PrintJson(stopped);
        }

        /// <summary>
        /// 执行模型部署只读、同步推理和异步推理样例。
        /// </summary>
        /// <param name="runner">SDK 高层操作入口。</param>
        /// <param name="cancellationToken">取消信号。</param>
        private static async Task RunModelDeploymentExamplesAsync(
            AMVisionOperationRunner runner,
            CancellationToken cancellationToken)
        {
            PrintSection("Model deployment runtime status");
            var status = await runner.GetModelDeploymentRuntimeStatusAsync(
                ModelDeploymentName,
                cancellationToken).ConfigureAwait(false);
            PrintJson(status);

            PrintSection("Model deployment runtime health");
            var health = await runner.GetModelDeploymentRuntimeHealthAsync(
                ModelDeploymentName,
                cancellationToken).ConfigureAwait(false);
            PrintJson(health);

            PrintSection("Model deployment invoke with configured input");
            var configuredInvoke = await runner.InvokeConfiguredModelDeploymentAsync(
                ModelDeploymentName,
                cancellationToken).ConfigureAwait(false);
            PrintJson(configuredInvoke);

            PrintSection("Model deployment invoke with image file");
            var fileInvoke = await runner.InvokeModelDeploymentWithImageFromFileAsync(
                ModelDeploymentName,
                ResolveImagePath(ImagePath),
                ImageMediaType,
                cancellationToken).ConfigureAwait(false);
            PrintJson(fileInvoke);

            PrintSection("Model deployment invoke with image bytes");
            var imageBytes = ReadImageBytes(ImagePath);
            var bytesInvoke = await runner.InvokeModelDeploymentWithImageBytesAsync(
                ModelDeploymentName,
                imageBytes,
                Path.GetFileName(ImagePath),
                ImageMediaType,
                cancellationToken).ConfigureAwait(false);
            PrintJson(bytesInvoke);

            PrintSection("Model deployment invoke with image base64");
            var imageBase64 = Convert.ToBase64String(imageBytes);
            var base64Invoke = await runner.InvokeModelDeploymentWithImageBase64Async(
                ModelDeploymentName,
                imageBase64,
                cancellationToken).ConfigureAwait(false);
            PrintJson(base64Invoke);

            PrintSection("Model deployment invoke with input file id");
            var fileIdInvoke = await runner.InvokeModelDeploymentWithInputFileIdAsync(
                ModelDeploymentName,
                InputFileId,
                cancellationToken).ConfigureAwait(false);
            PrintJson(fileIdInvoke);

            PrintSection("Model deployment invoke with input uri");
            var uriInvoke = await runner.InvokeModelDeploymentWithInputUriAsync(
                ModelDeploymentName,
                InputUri,
                cancellationToken).ConfigureAwait(false);
            PrintJson(uriInvoke);

            PrintSection("Model deployment async run with configured input");
            var configuredRun = await runner.RunConfiguredModelDeploymentAsync(
                ModelDeploymentName,
                cancellationToken).ConfigureAwait(false);
            PrintJson(configuredRun);

            PrintSection("Model deployment async run with image file");
            var fileRun = await runner.RunModelDeploymentWithImageFromFileAsync(
                ModelDeploymentName,
                ResolveImagePath(ImagePath),
                ImageMediaType,
                cancellationToken).ConfigureAwait(false);
            PrintJson(fileRun);

            PrintSection("Model deployment async run with image bytes");
            var bytesRun = await runner.RunModelDeploymentWithImageBytesAsync(
                ModelDeploymentName,
                imageBytes,
                Path.GetFileName(ImagePath),
                ImageMediaType,
                cancellationToken).ConfigureAwait(false);
            PrintJson(bytesRun);

            PrintSection("Model deployment async run with image base64");
            var base64Run = await runner.RunModelDeploymentWithImageBase64Async(
                ModelDeploymentName,
                imageBase64,
                cancellationToken).ConfigureAwait(false);
            PrintJson(base64Run);

            PrintSection("Model deployment async run with input file id");
            var fileIdRun = await runner.RunModelDeploymentWithInputFileIdAsync(
                ModelDeploymentName,
                InputFileId,
                cancellationToken).ConfigureAwait(false);
            PrintJson(fileIdRun);

            PrintSection("Model deployment async run with input uri");
            var uriRun = await runner.RunModelDeploymentWithInputUriAsync(
                ModelDeploymentName,
                InputUri,
                cancellationToken).ConfigureAwait(false);
            PrintJson(uriRun);

            PrintSection("Model inference task detail");
            var taskDetail = await runner.GetModelInferenceTaskAsync(
                ModelDeploymentName,
                InferenceTaskId,
                includeEvents: true,
                cancellationToken: cancellationToken).ConfigureAwait(false);
            PrintJson(taskDetail);

            PrintSection("Model inference task result");
            var taskResult = await runner.GetModelInferenceTaskResultAsync(
                ModelDeploymentName,
                InferenceTaskId,
                cancellationToken).ConfigureAwait(false);
            PrintJson(taskResult);
        }

        /// <summary>
        /// 执行模型部署启停类样例。
        /// </summary>
        /// <param name="runner">SDK 高层操作入口。</param>
        /// <param name="cancellationToken">取消信号。</param>
        private static async Task RunModelDeploymentMutationExamplesAsync(
            AMVisionOperationRunner runner,
            CancellationToken cancellationToken)
        {
            PrintSection("Model deployment start");
            var started = await runner.StartModelDeploymentRuntimeAsync(
                ModelDeploymentName,
                cancellationToken).ConfigureAwait(false);
            PrintJson(started);

            PrintSection("Model deployment warmup");
            var warmup = await runner.WarmupModelDeploymentRuntimeAsync(
                ModelDeploymentName,
                cancellationToken).ConfigureAwait(false);
            PrintJson(warmup);

            PrintSection("Model deployment reset");
            var reset = await runner.ResetModelDeploymentRuntimeAsync(
                ModelDeploymentName,
                cancellationToken).ConfigureAwait(false);
            PrintJson(reset);

            PrintSection("Model deployment stop");
            var stopped = await runner.StopModelDeploymentRuntimeAsync(
                ModelDeploymentName,
                cancellationToken).ConfigureAwait(false);
            PrintJson(stopped);
        }

        /// <summary>
        /// 执行 TriggerSource 管理只读样例。
        /// </summary>
        /// <param name="runner">SDK 高层操作入口。</param>
        /// <param name="cancellationToken">取消信号。</param>
        private static async Task RunTriggerSourceExamplesAsync(
            AMVisionOperationRunner runner,
            CancellationToken cancellationToken)
        {
            PrintSection("TriggerSource list");
            var triggerSources = await runner.ListTriggerSourcesAsync(
                RuntimeName,
                cancellationToken).ConfigureAwait(false);
            PrintJson(triggerSources);

            PrintSection("TriggerSource detail");
            var triggerSource = await runner.GetTriggerSourceAsync(
                TriggerSourceName,
                cancellationToken).ConfigureAwait(false);
            PrintJson(triggerSource);

            PrintSection("TriggerSource health");
            var health = await runner.GetTriggerSourceHealthAsync(
                TriggerSourceName,
                cancellationToken).ConfigureAwait(false);
            PrintJson(health);
        }

        /// <summary>
        /// 执行 TriggerSource 启停样例。
        /// </summary>
        /// <param name="runner">SDK 高层操作入口。</param>
        /// <param name="cancellationToken">取消信号。</param>
        private static async Task RunTriggerSourceMutationExamplesAsync(
            AMVisionOperationRunner runner,
            CancellationToken cancellationToken)
        {
            PrintSection("TriggerSource enable");
            var enabled = await runner.EnableTriggerSourceAsync(
                TriggerSourceName,
                cancellationToken).ConfigureAwait(false);
            PrintJson(enabled);

            PrintSection("TriggerSource disable");
            var disabled = await runner.DisableTriggerSourceAsync(
                TriggerSourceName,
                cancellationToken).ConfigureAwait(false);
            PrintJson(disabled);
        }

        /// <summary>
        /// 执行 ZeroMQ TriggerSource 调用样例。
        /// </summary>
        /// <param name="runner">SDK 高层操作入口。</param>
        /// <param name="cancellationToken">取消信号。</param>
        private static async Task RunZeroMqTriggerExamplesAsync(
            AMVisionOperationRunner runner,
            CancellationToken cancellationToken)
        {
            PrintSection("ZeroMQ event trigger");
            var payload = new Dictionary<string, object?>
            {
                ["source"] = "dotnet-console",
                ["message"] = "hello"
            };
            var eventResult = await runner.InvokeZeroMqEventAsync(
                TriggerSourceName,
                payload,
                cancellationToken).ConfigureAwait(false);
            PrintJson(eventResult);

            PrintSection("ZeroMQ image trigger with configured image");
            var configuredImageResult = await runner.InvokeConfiguredZeroMqImageAsync(
                TriggerSourceName,
                cancellationToken).ConfigureAwait(false);
            PrintJson(configuredImageResult);

            PrintSection("ZeroMQ image trigger with image file");
            var fileImageResult = await runner.InvokeZeroMqImageFromFileAsync(
                TriggerSourceName,
                ResolveImagePath(ImagePath),
                ImageMediaType,
                cancellationToken).ConfigureAwait(false);
            PrintJson(fileImageResult);

            PrintSection("ZeroMQ image trigger with image bytes");
            var imageBytes = ReadImageBytes(ImagePath);
            var bytesImageResult = await runner.InvokeZeroMqImageBytesAsync(
                TriggerSourceName,
                imageBytes,
                ImageMediaType,
                cancellationToken).ConfigureAwait(false);
            PrintJson(bytesImageResult);

            PrintSection("ZeroMQ image trigger with image base64");
            var imageBase64 = Convert.ToBase64String(imageBytes);
            var base64ImageResult = await runner.InvokeZeroMqImageBase64Async(
                TriggerSourceName,
                imageBase64,
                ImageMediaType,
                cancellationToken).ConfigureAwait(false);
            PrintJson(base64ImageResult);

            PrintSection("ZeroMQ BGR24 trigger with configured image");
            var configuredBgr24Result = await runner.InvokeConfiguredZeroMqBgr24ImageAsync(
                TriggerSourceName,
                cancellationToken).ConfigureAwait(false);
            PrintJson(configuredBgr24Result);

            PrintSection("ZeroMQ BGR24 trigger with image file");
            var fileBgr24Result = await runner.InvokeZeroMqBgr24FromFileAsync(
                TriggerSourceName,
                ResolveImagePath(ImagePath),
                cancellationToken).ConfigureAwait(false);
            PrintJson(fileBgr24Result);

            PrintSection("ZeroMQ BGR24 trigger with Bitmap");
            using (var bitmap = new Bitmap(ResolveImagePath(ImagePath)))
            {
                var bitmapBgr24Result = await runner.InvokeZeroMqBgr24FromBitmapAsync(
                    TriggerSourceName,
                    bitmap,
                    cancellationToken).ConfigureAwait(false);
                PrintJson(bitmapBgr24Result);
            }

            PrintSection("ZeroMQ BGR24 trigger with raw bytes");
            var frame = ImageConversionTools.ImageFileToBgr24(ResolveImagePath(ImagePath));
            var rawBgr24Result = await runner.InvokeZeroMqBgr24Async(
                TriggerSourceName,
                frame.Bytes,
                frame.Width,
                frame.Height,
                cancellationToken).ConfigureAwait(false);
            PrintJson(rawBgr24Result);
        }

        /// <summary>
        /// 执行 SDK 图片转换工具样例。
        /// </summary>
        private static void RunImageConversionToolExamples()
        {
            PrintSection("Image conversion tools");

            var imagePath = ResolveImagePath(ImagePath);
            var inferredFormat = ImageConversionTools.InferFormatFromPath(imagePath);
            var mediaType = ImageConversionTools.GetMediaType(inferredFormat);
            var base64 = ImageConversionTools.ImageFileToBase64(imagePath, inferredFormat);

            var frame = ImageConversionTools.ImageFileToBgr24(imagePath);
            var previewBytes = ImageConversionTools.Bgr24ToImageBytes(
                frame.Bytes,
                frame.Width,
                frame.Height,
                ImageFileFormat.JPEG,
                jpegQuality: 85L);

            var summary = new Dictionary<string, object?>
            {
                ["image_path"] = imagePath,
                ["format"] = inferredFormat.ToString(),
                ["media_type"] = mediaType,
                ["base64_length"] = base64.Length,
                ["bgr24_width"] = frame.Width,
                ["bgr24_height"] = frame.Height,
                ["preview_jpeg_bytes"] = previewBytes.Length
            };

            PrintJson(summary);
        }

        /// <summary>
        /// 输出 JSON，便于现场复制和排查。
        /// </summary>
        /// <param name="value">待输出对象。</param>
        private static void PrintJson(object value)
        {
            var json = JsonConvert.SerializeObject(value, Formatting.Indented);
            System.Console.WriteLine(json);
        }

        /// <summary>
        /// 输出分段标题。
        /// </summary>
        /// <param name="title">标题。</param>
        private static void PrintSection(string title)
        {
            System.Console.WriteLine();
            System.Console.WriteLine("==== " + title + " ====");
        }

        /// <summary>
        /// 输出后端连接检查摘要，避免默认调试调用打印过大的系统配置。
        /// </summary>
        /// <param name="response">系统配置响应。</param>
        private static void PrintHealthSummary(SystemConfigResponse response)
        {
            if (response == null)
            {
                throw new ArgumentNullException(nameof(response));
            }

            PrintSection("Backend health");

            var localBufferBroker = response.LocalBufferBroker;
            var summary = new Dictionary<string, object?>
            {
                ["state"] = "ok",
                ["format_id"] = response.FormatId,
                ["local_buffer_broker_enabled"] = localBufferBroker?.Enabled,
                ["local_buffer_broker_default_pool"] = localBufferBroker?.DefaultPoolName
            };

            PrintJson(summary);
        }

        /// <summary>
        /// 读取图片文件 bytes。
        /// </summary>
        /// <param name="imagePath">图片文件路径。</param>
        /// <returns>图片 bytes。</returns>
        private static byte[] ReadImageBytes(string imagePath)
        {
            var resolvedPath = ResolveImagePath(imagePath);
            var bytes = File.ReadAllBytes(resolvedPath);
            return bytes;
        }

        /// <summary>
        /// 解析图片路径，并确认文件存在。
        /// </summary>
        /// <param name="imagePath">图片路径。</param>
        /// <returns>绝对图片路径。</returns>
        private static string ResolveImagePath(string imagePath)
        {
            if (string.IsNullOrWhiteSpace(imagePath))
            {
                throw new ArgumentException("Image path is required.", nameof(imagePath));
            }

            var resolvedPath = Path.IsPathRooted(imagePath)
                ? imagePath
                : Path.GetFullPath(Path.Combine(AppDomain.CurrentDomain.BaseDirectory, imagePath));

            if (!File.Exists(resolvedPath))
            {
                resolvedPath = Path.IsPathRooted(imagePath)
                    ? imagePath
                    : Path.GetFullPath(imagePath);
            }

            if (!File.Exists(resolvedPath))
            {
                throw new FileNotFoundException("Image file was not found.", resolvedPath);
            }

            return resolvedPath;
        }

        /// <summary>
        /// 拼接配置 key 列表。
        /// </summary>
        /// <param name="names">配置 key 列表。</param>
        /// <returns>显示用文本。</returns>
        private static string JoinNames(IReadOnlyList<string> names)
        {
            if (names == null || names.Count == 0)
            {
                return "(none)";
            }

            return string.Join(", ", names);
        }

        /// <summary>
        /// 输出 HTTP API 异常详情。
        /// </summary>
        /// <param name="exception">SDK HTTP API 异常。</param>
        private static void WriteApiException(AMVisionApiException exception)
        {
            System.Console.Error.WriteLine("HTTP API call failed:");
            System.Console.Error.WriteLine(exception.Message);
            System.Console.Error.WriteLine("StatusCode: " + (int)exception.StatusCode);

            if (!string.IsNullOrWhiteSpace(exception.ErrorCode))
            {
                System.Console.Error.WriteLine("ErrorCode: " + exception.ErrorCode);
            }

            if (exception.Details.Count > 0)
            {
                System.Console.Error.WriteLine("Details:");
                System.Console.Error.WriteLine(JsonConvert.SerializeObject(exception.Details, Formatting.Indented));
            }

            if (!string.IsNullOrWhiteSpace(exception.ResponseBody))
            {
                System.Console.Error.WriteLine("ResponseBody:");
                System.Console.Error.WriteLine(exception.ResponseBody);
            }
        }

        /// <summary>
        /// 输出 ZeroMQ TriggerSource 异常详情。
        /// </summary>
        /// <param name="exception">SDK TriggerSource 异常。</param>
        private static void WriteTriggerException(AMVisionTriggerException exception)
        {
            System.Console.Error.WriteLine("ZeroMQ TriggerSource call failed:");
            System.Console.Error.WriteLine(exception.Message);
            System.Console.Error.WriteLine("ErrorCode: " + exception.ErrorCode);

            if (exception.Details.Count > 0)
            {
                System.Console.Error.WriteLine("Details:");
                System.Console.Error.WriteLine(JsonConvert.SerializeObject(exception.Details, Formatting.Indented));
            }
        }

        /// <summary>
        /// 输出已知异常。
        /// </summary>
        /// <param name="title">错误标题。</param>
        /// <param name="exception">异常对象。</param>
        private static void WriteKnownException(string title, Exception exception)
        {
            System.Console.Error.WriteLine(title + ":");
            System.Console.Error.WriteLine(exception.Message);

            if (exception.InnerException != null)
            {
                System.Console.Error.WriteLine("InnerException:");
                System.Console.Error.WriteLine(exception.InnerException.Message);
            }
        }

        /// <summary>
        /// 在人工启动控制台时等待按键，避免窗口立即关闭。
        /// </summary>
        private static void WaitForKeyIfInteractive()
        {
            if (System.Console.IsInputRedirected)
            {
                return;
            }

            System.Console.WriteLine();
            System.Console.WriteLine("Press any key to exit.");
            System.Console.ReadKey(intercept: true);
        }
    }
}
