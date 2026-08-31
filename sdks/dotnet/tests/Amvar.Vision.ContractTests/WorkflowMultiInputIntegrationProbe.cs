using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Security.Cryptography;
using System.Text;
using Amvar.Vision.SharedMemory;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

namespace Amvar.Vision.ContractTests
{
    /// <summary>使用 SDK 配置包执行 HTTP、ZeroMQ 和 LocalBuffer 多输入真实调用。</summary>
    internal static class WorkflowMultiInputIntegrationProbe
    {
        private const int ExpectedArgumentCount = 11;

        internal static int Run(string[] args)
        {
            if (args.Length != ExpectedArgumentCount)
            {
                return 64;
            }

            var outputPath = Path.GetFullPath(args[10]);
            try
            {
                var options = ProbeOptions.Parse(args);
                var report = Execute(options);
                WriteReport(outputPath, report);
                return 0;
            }
            catch (Exception error)
            {
                WriteReport(outputPath, new
                {
                    format_id = "amvision.workflow-multi-input-sdk-probe.v1",
                    succeeded = false,
                    error_type = error.GetType().FullName,
                    error.Message,
                    error.StackTrace,
                    inner_type = error.InnerException?.GetType().FullName,
                    inner_message = error.InnerException?.Message
                });
                return 1;
            }
        }

        private static object Execute(ProbeOptions options)
        {
            var imageBytes = File.ReadAllBytes(options.ImagePath);
            var samples = new List<object>();
            using (var runner = AMVisionOperationRunner.CreateFromConfigDirectory(options.ConfigDirectory))
            {
                for (var sequence = 0; sequence < options.Iterations; sequence += 1)
                {
                    var http = InvokeHttp(runner, options, imageBytes, sequence);
                    var zeroMq = InvokeZeroMq(runner, options, sequence);
                    var sharedMemory = InvokeSharedMemory(runner, options, sequence);
                    samples.Add(new
                    {
                        sequence,
                        http,
                        zeromq = zeroMq,
                        local_shared_memory = sharedMemory
                    });
                }
            }

            return new
            {
                format_id = "amvision.workflow-multi-input-sdk-probe.v1",
                succeeded = true,
                options.RuntimeName,
                options.ZeroMqTriggerName,
                options.SharedMemoryTriggerName,
                options.Iterations,
                image_path = options.ImagePath,
                image_size_bytes = imageBytes.LongLength,
                samples
            };
        }

        private static object InvokeHttp(
            AMVisionOperationRunner runner,
            ProbeOptions options,
            byte[] imageBytes,
            int sequence)
        {
            var builder = runner.CreateWorkflowRequestBuilder(options.RuntimeName)
                .AddImage(
                    "request_image_ref",
                    () => OpenSequentialRead(options.ImagePath),
                    Path.GetFileName(options.ImagePath),
                    options.ImageMediaType,
                    imageBytes.LongLength)
                .AddImageBase64(
                    "request_image_base64",
                    imageBytes,
                    options.ImageMediaType)
                .AddJson("request_json", new
                {
                    station = 2,
                    recipe = "3570",
                    transport = "http-runtime",
                    sequence
                })
                .AddText(
                    "request_text",
                    "3570 fixture validation " + sequence.ToString(CultureInfo.InvariantCulture))
                .AddFile(
                    "request_file",
                    () => OpenSequentialRead(options.JsonFilePath),
                    Path.GetFileName(options.JsonFilePath),
                    "application/json",
                    new FileInfo(options.JsonFilePath).Length)
                .AddFiles(
                    "request_files",
                    new[]
                    {
                        WorkflowUploadFile.FromFile(options.TextFilePath1, "text/plain"),
                        WorkflowUploadFile.FromFile(options.TextFilePath2, "text/plain")
                    })
                .AddExecutionMetadata("sdk_probe", "multi-input-http")
                .AddExecutionMetadata("sequence", sequence)
                .WithTimeoutSeconds(120);

            var startedAt = Stopwatch.GetTimestamp();
            var result = runner.InvokeRuntimeAppResultAsync(
                    options.RuntimeName,
                    builder.BuildMultipart())
                .GetAwaiter()
                .GetResult();
            var elapsedMs = ElapsedMilliseconds(startedAt);
            var resultJson = result.BodyJson.ToString(Formatting.None);
            return new
            {
                succeeded = true,
                elapsed_ms = elapsedMs,
                result_token_type = result.BodyJson.Type.ToString(),
                result_sha256 = ComputeSha256(resultJson),
                result_size_bytes = Encoding.UTF8.GetByteCount(resultJson)
            };
        }

        private static object InvokeZeroMq(
            AMVisionOperationRunner runner,
            ProbeOptions options,
            int sequence)
        {
            var inputs = runner.CreateWorkflowTriggerInputsBuilder(options.ZeroMqTriggerName)
                .AddJson("request_json", new
                {
                    station = 2,
                    recipe = "3570",
                    transport = "zeromq-topic",
                    sequence
                })
                .AddText(
                    "request_text",
                    "3570 fixture validation " + sequence.ToString(CultureInfo.InvariantCulture))
                .Build();
            var startedAt = Stopwatch.GetTimestamp();
            var result = runner.InvokeZeroMqImageFromFileWithInputs(
                options.ZeroMqTriggerName,
                options.ImagePath,
                inputs,
                options.ImageMediaType);
            var elapsedMs = ElapsedMilliseconds(startedAt);
            RequireSucceeded("ZeroMQ", result);
            return BuildTriggerSample(result, elapsedMs, result.ImageAttachments.Count);
        }

        private static object InvokeSharedMemory(
            AMVisionOperationRunner runner,
            ProbeOptions options,
            int sequence)
        {
            var inputs = runner.CreateWorkflowTriggerInputsBuilder(options.SharedMemoryTriggerName)
                .AddJson("request_json", new
                {
                    station = 2,
                    recipe = "3570",
                    transport = "local-shared-memory",
                    sequence
                })
                .AddText(
                    "request_text",
                    "3570 fixture validation " + sequence.ToString(CultureInfo.InvariantCulture))
                .Build();
            var startedAt = Stopwatch.GetTimestamp();
            using (var result = runner.InvokeSharedMemoryImageFromFileWithInputs(
                options.SharedMemoryTriggerName,
                options.ImagePath,
                inputs,
                options.ImageMediaType))
            {
                var elapsedMs = ElapsedMilliseconds(startedAt);
                RequireSucceeded("LocalBuffer", result.Result);
                return BuildTriggerSample(result.Result, elapsedMs, result.Attachments.Count);
            }
        }

        private static object BuildTriggerSample(
            TriggerResult result,
            double elapsedMs,
            int attachmentCount)
        {
            var responseJson = JsonConvert.SerializeObject(result.ResponsePayload, Formatting.None);
            return new
            {
                succeeded = true,
                elapsed_ms = elapsedMs,
                result.TriggerSourceId,
                result.WorkflowRunId,
                response_keys = result.ResponsePayload.Keys.OrderBy(item => item, StringComparer.Ordinal).ToArray(),
                response_sha256 = ComputeSha256(responseJson),
                response_size_bytes = Encoding.UTF8.GetByteCount(responseJson),
                attachment_count = attachmentCount
            };
        }

        private static void RequireSucceeded(string transport, TriggerResult result)
        {
            if (!string.Equals(result.State, "succeeded", StringComparison.OrdinalIgnoreCase))
            {
                throw new InvalidOperationException(
                    transport + " Workflow result failed: " + result.ErrorMessage);
            }
        }

        private static FileStream OpenSequentialRead(string path)
        {
            return new FileStream(
                path,
                FileMode.Open,
                FileAccess.Read,
                FileShare.Read,
                1024 * 1024,
                FileOptions.SequentialScan);
        }

        private static double ElapsedMilliseconds(long startedAt)
        {
            return (Stopwatch.GetTimestamp() - startedAt) * 1000.0 / Stopwatch.Frequency;
        }

        private static string ComputeSha256(string value)
        {
            using (var sha256 = SHA256.Create())
            {
                var hash = sha256.ComputeHash(Encoding.UTF8.GetBytes(value));
                var builder = new StringBuilder(hash.Length * 2);
                foreach (var item in hash)
                {
                    builder.Append(item.ToString("x2", CultureInfo.InvariantCulture));
                }
                return builder.ToString();
            }
        }

        private static void WriteReport(string outputPath, object report)
        {
            Directory.CreateDirectory(Path.GetDirectoryName(outputPath) ?? ".");
            File.WriteAllText(outputPath, JsonConvert.SerializeObject(report, Formatting.Indented));
        }

        private sealed class ProbeOptions
        {
            internal string ConfigDirectory { get; private set; } = string.Empty;
            internal string RuntimeName { get; private set; } = string.Empty;
            internal string ZeroMqTriggerName { get; private set; } = string.Empty;
            internal string SharedMemoryTriggerName { get; private set; } = string.Empty;
            internal string ImagePath { get; private set; } = string.Empty;
            internal string ImageMediaType { get; private set; } = string.Empty;
            internal string JsonFilePath { get; private set; } = string.Empty;
            internal string TextFilePath1 { get; private set; } = string.Empty;
            internal string TextFilePath2 { get; private set; } = string.Empty;
            internal int Iterations { get; private set; }

            internal static ProbeOptions Parse(string[] args)
            {
                var result = new ProbeOptions
                {
                    ConfigDirectory = RequireDirectory(args[1]),
                    RuntimeName = RequireText(args[2], "runtimeName"),
                    ZeroMqTriggerName = RequireText(args[3], "zeroMqTriggerName"),
                    SharedMemoryTriggerName = RequireText(args[4], "sharedMemoryTriggerName"),
                    ImagePath = RequireFile(args[5]),
                    JsonFilePath = RequireFile(args[6]),
                    TextFilePath1 = RequireFile(args[7]),
                    TextFilePath2 = RequireFile(args[8]),
                    Iterations = int.Parse(args[9], CultureInfo.InvariantCulture)
                };
                if (result.Iterations <= 0 || result.Iterations > 50)
                {
                    throw new ArgumentOutOfRangeException("iterations");
                }
                result.ImageMediaType = ResolveImageMediaType(result.ImagePath);
                return result;
            }

            private static string ResolveImageMediaType(string path)
            {
                switch (Path.GetExtension(path).ToLowerInvariant())
                {
                    case ".bmp":
                        return "image/bmp";
                    case ".png":
                        return "image/png";
                    case ".jpg":
                    case ".jpeg":
                        return "image/jpeg";
                    default:
                        throw new InvalidOperationException(
                            "Probe image extension is not supported: " + path);
                }
            }

            private static string RequireDirectory(string value)
            {
                var path = Path.GetFullPath(RequireText(value, "configDirectory"));
                return Directory.Exists(path)
                    ? path
                    : throw new DirectoryNotFoundException(path);
            }

            private static string RequireFile(string value)
            {
                var path = Path.GetFullPath(RequireText(value, "filePath"));
                return File.Exists(path)
                    ? path
                    : throw new FileNotFoundException("Probe input does not exist.", path);
            }

            private static string RequireText(string value, string parameterName)
            {
                if (string.IsNullOrWhiteSpace(value))
                {
                    throw new ArgumentException(parameterName + " cannot be empty.", parameterName);
                }
                return value.Trim();
            }
        }
    }
}
