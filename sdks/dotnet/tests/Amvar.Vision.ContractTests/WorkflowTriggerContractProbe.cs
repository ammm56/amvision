using System;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Security.Cryptography;
using System.Threading;
using Amvar.Vision.SharedMemory;
using Newtonsoft.Json;

namespace Amvar.Vision.ContractTests
{
    internal static class WorkflowTriggerContractProbe
    {
        internal static int? TryRun(string[] args)
        {
            if (args.Length == 0)
            {
                return null;
            }

            switch (args[0])
            {
                case "--hold-byte-lock":
                    return HoldByteLock(args);
                case "--try-byte-lock":
                    return TryByteLock(args);
                case "--checksum-file":
                    return BenchmarkChecksum(args);
                case "--invoke-shared-memory":
                    return InvokeSharedMemory(args);
                case "--invoke-shared-memory-output":
                    return InvokeSharedMemoryOutput(args);
                case "--invoke-shared-memory-input":
                    return InvokeSharedMemoryInput(args);
                case "--benchmark-workflow-trigger":
                    return WorkflowTriggerBenchmarkProbe.Run(args);
                default:
                    return null;
            }
        }

        private static int HoldByteLock(string[] args)
        {
            if (args.Length != 4)
            {
                return 64;
            }

            var durationMilliseconds = int.Parse(args[3], CultureInfo.InvariantCulture);
            using (var stream = OpenLockFile(args[1]))
            {
                stream.Lock(0, 1);
                try
                {
                    File.WriteAllText(args[2], "ready");
                    Thread.Sleep(durationMilliseconds);
                }
                finally
                {
                    stream.Unlock(0, 1);
                }
            }

            return 0;
        }

        private static int TryByteLock(string[] args)
        {
            if (args.Length != 2)
            {
                return 64;
            }

            try
            {
                using (var stream = OpenLockFile(args[1]))
                {
                    stream.Lock(0, 1);
                    stream.Unlock(0, 1);
                }

                return 0;
            }
            catch (IOException)
            {
                return 2;
            }
        }

        private static int BenchmarkChecksum(string[] args)
        {
            if (args.Length != 5)
            {
                return 64;
            }

            var algorithm = args[1];
            var input = File.ReadAllBytes(args[2]);
            var chunkSize = int.Parse(args[3], CultureInfo.InvariantCulture);
            var iterations = int.Parse(args[4], CultureInfo.InvariantCulture);
            if (chunkSize <= 0 || iterations <= 0)
            {
                return 64;
            }

            ComputeChecksum(algorithm, input, chunkSize);
            var stopwatch = Stopwatch.StartNew();
            string value = string.Empty;
            for (var iteration = 0; iteration < iterations; iteration += 1)
            {
                value = ComputeChecksum(algorithm, input, chunkSize);
            }

            stopwatch.Stop();
            var elapsedMilliseconds = stopwatch.Elapsed.TotalMilliseconds / iterations;
            Console.WriteLine(
                "{{\"algorithm\":\"{0}\",\"size_bytes\":{1},\"chunk_size\":{2}," +
                "\"iterations\":{3},\"elapsed_ms\":{4},\"value\":\"{5}\"}}",
                algorithm,
                input.Length,
                chunkSize,
                iterations,
                elapsedMilliseconds.ToString("F6", CultureInfo.InvariantCulture),
                value);
            return 0;
        }

        private static int InvokeSharedMemory(string[] args)
        {
            if (args.Length != 6)
            {
                return 64;
            }

            try
            {
                var routeGeneration = long.Parse(args[3], CultureInfo.InvariantCulture);
                var imageBytes = File.ReadAllBytes(args[4]);
                using (var client = new SharedMemoryTriggerClient(BuildSharedMemoryOptions(
                    args[1],
                    args[2],
                    routeGeneration)))
                using (var result = client.InvokeImageBytes(
                    imageBytes,
                    "application/octet-stream",
                    new SharedMemoryTriggerRequest
                    {
                        EventId = "dotnet-stage6-event",
                        TraceId = "dotnet-stage6-trace"
                    }))
                {
                    File.WriteAllText(
                        args[5],
                        JsonConvert.SerializeObject(new
                        {
                            result.Result.FormatId,
                            result.Result.State,
                            result.Result.WorkflowRunId,
                            AttachmentCount = result.Attachments.Count
                        }));
                }

                return 0;
            }
            catch (Exception error)
            {
                File.WriteAllText(
                    args[5],
                    JsonConvert.SerializeObject(new
                    {
                        ErrorType = error.GetType().FullName,
                        error.Message,
                        error.StackTrace,
                        InnerType = error.InnerException?.GetType().FullName,
                        InnerMessage = error.InnerException?.Message
                    }));
                return 1;
            }
        }

        private static int InvokeSharedMemoryOutput(string[] args)
        {
            if (args.Length != 8)
            {
                return 64;
            }

            try
            {
                var imageBytes = File.ReadAllBytes(args[4]);
                SharedMemoryTriggerTimings? timings = null;
                using (var client = new SharedMemoryTriggerClient(BuildSharedMemoryOptions(
                    args[1],
                    args[2],
                    long.Parse(args[3], CultureInfo.InvariantCulture))))
                {
                    using (var result = client.InvokeImageBytes(
                        imageBytes,
                        "application/octet-stream",
                        new SharedMemoryTriggerRequest { EnableTimings = true }))
                    {
                        timings = result.Timings;
                        if (result.Attachments.Count != 1)
                        {
                            throw new InvalidOperationException("Expected exactly one output attachment.");
                        }

                        using (var read = result.Attachments[0].OpenRead())
                        {
                            File.WriteAllText(args[5], "ready");
                            var deadline = Stopwatch.StartNew();
                            while (!File.Exists(args[6]) && deadline.Elapsed < TimeSpan.FromSeconds(10))
                            {
                                Thread.Sleep(5);
                            }

                            if (!File.Exists(args[6]))
                            {
                                throw new TimeoutException("Timed out waiting for output release signal.");
                            }

                            using (var output = new FileStream(args[7], FileMode.Create, FileAccess.Write, FileShare.Read))
                            {
                                read.Stream.CopyTo(output);
                            }
                        }
                    }
                }

                File.WriteAllText(
                    args[7] + ".timings.json",
                    JsonConvert.SerializeObject(timings));

                return 0;
            }
            catch (Exception error)
            {
                File.WriteAllText(args[7] + ".error.json", JsonConvert.SerializeObject(new
                {
                    ErrorType = error.GetType().FullName,
                    error.Message,
                    error.StackTrace,
                    InnerType = error.InnerException?.GetType().FullName,
                    InnerMessage = error.InnerException?.Message
                }));
                return 1;
            }
        }

        private static int InvokeSharedMemoryInput(string[] args)
        {
            if (args.Length != 10)
            {
                return 64;
            }

            try
            {
                var mode = args[4];
                var inputPath = args[5];
                var width = int.Parse(args[7], CultureInfo.InvariantCulture);
                var height = int.Parse(args[8], CultureInfo.InvariantCulture);
                var rowStride = int.Parse(args[9], CultureInfo.InvariantCulture);
                using (var client = new SharedMemoryTriggerClient(BuildSharedMemoryOptions(
                    args[1],
                    args[2],
                    long.Parse(args[3], CultureInfo.InvariantCulture))))
                using (var result = InvokeInputMode(
                    client,
                    mode,
                    inputPath,
                    width,
                    height,
                    rowStride))
                {
                    File.WriteAllText(
                        args[6],
                        JsonConvert.SerializeObject(new
                        {
                            result.Result.State,
                            result.Result.WorkflowRunId,
                            AttachmentCount = result.Attachments.Count,
                            Mode = mode,
                            result.Timings
                        }));
                }

                return 0;
            }
            catch (Exception error)
            {
                File.WriteAllText(
                    args[6],
                    JsonConvert.SerializeObject(new
                    {
                        ErrorType = error.GetType().FullName,
                        error.Message,
                        error.StackTrace,
                        InnerType = error.InnerException?.GetType().FullName,
                        InnerMessage = error.InnerException?.Message
                    }));
                return 1;
            }
        }

        private static SharedMemoryTriggerResult InvokeInputMode(
            SharedMemoryTriggerClient client,
            string mode,
            string inputPath,
            int width,
            int height,
            int rowStride)
        {
            var input = File.ReadAllBytes(inputPath);
            var request = new SharedMemoryTriggerRequest
            {
                EventId = "dotnet-stage6-" + mode,
                TraceId = "dotnet-stage6-input-conversion",
                EnableTimings = true
            };
            switch (mode)
            {
                case "encoded-bytes":
                    return client.InvokeImageBytes(input, "image/png", request);
                case "encoded-file":
                    return client.InvokeImageFromFile(inputPath, request: request);
                case "base64":
                    return client.InvokeImageBase64(
                        "data:image/png;base64," + Convert.ToBase64String(input),
                        request: request);
                case "bgr24":
                    return client.InvokeBgr24(input, width, height, request);
                case "bgr24-direct":
                    return client.InvokeBgr24(
                        width,
                        height,
                        destination => input.AsSpan().CopyTo(destination),
                        request);
                case "bgr24-stride":
                    return client.InvokeBgr24(input, width, height, rowStride, request);
                case "mono8-stride":
                    return client.InvokeMono8(input, width, height, rowStride, request);
                case "bitmap":
                    using (var bitmap = new System.Drawing.Bitmap(inputPath))
                    {
                        return client.InvokeBitmap(bitmap, request);
                    }
                default:
                    throw new ArgumentException("Unsupported input conversion mode.", nameof(mode));
            }
        }

        private static SharedMemoryTriggerClientOptions BuildSharedMemoryOptions(
            string buffersRoot,
            string triggerSourceId,
            long routeGeneration)
        {
            return new SharedMemoryTriggerClientOptions
            {
                BuffersRoot = buffersRoot,
                TriggerSourceId = triggerSourceId,
                RouteGeneration = routeGeneration,
                Timeout = TimeSpan.FromSeconds(10)
            };
        }

        private static string ComputeChecksum(string algorithm, byte[] input, int chunkSize)
        {
            if (string.Equals(algorithm, "crc32-ieee", StringComparison.Ordinal))
            {
                var checksum = new Crc32Ieee();
                for (var offset = 0; offset < input.Length; offset += chunkSize)
                {
                    checksum.Append(input, offset, Math.Min(chunkSize, input.Length - offset));
                }

                return checksum.Value.ToString("x8", CultureInfo.InvariantCulture);
            }

            if (string.Equals(algorithm, "sha256", StringComparison.Ordinal))
            {
                using (var checksum = SHA256.Create())
                {
                    for (var offset = 0; offset < input.Length; offset += chunkSize)
                    {
                        var count = Math.Min(chunkSize, input.Length - offset);
                        if (offset + count < input.Length)
                        {
                            checksum.TransformBlock(input, offset, count, input, offset);
                        }
                        else
                        {
                            checksum.TransformFinalBlock(input, offset, count);
                        }
                    }

                    return ToHex(checksum.Hash ?? Array.Empty<byte>());
                }
            }

            throw new ArgumentException("不支持的 checksum 算法。", nameof(algorithm));
        }

        private static FileStream OpenLockFile(string path)
        {
            return new FileStream(
                path,
                FileMode.OpenOrCreate,
                FileAccess.ReadWrite,
                FileShare.ReadWrite | FileShare.Delete,
                1,
                FileOptions.None);
        }

        private static string ToHex(byte[] input)
        {
            var result = new char[input.Length * 2];
            const string alphabet = "0123456789abcdef";
            for (var index = 0; index < input.Length; index += 1)
            {
                result[index * 2] = alphabet[input[index] >> 4];
                result[index * 2 + 1] = alphabet[input[index] & 0xf];
            }

            return new string(result);
        }
    }
}
