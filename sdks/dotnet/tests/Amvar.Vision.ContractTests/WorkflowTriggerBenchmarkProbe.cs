using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Linq;
using Amvar.Vision.SharedMemory;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

namespace Amvar.Vision.ContractTests
{
    /// <summary>在单个 .NET 进程内执行真实 ZeroMQ 或共享内存 Trigger 基准。</summary>
    internal static class WorkflowTriggerBenchmarkProbe
    {
        internal static int Run(string[] args)
        {
            if (args.Length != 3)
            {
                return 64;
            }

            BenchmarkConfig? config = null;
            try
            {
                config = JsonConvert.DeserializeObject<BenchmarkConfig>(File.ReadAllText(args[1]));
                if (config == null)
                {
                    throw new InvalidDataException("Benchmark config must be a JSON object.");
                }

                config.Validate();
                var report = Execute(config);
                WriteReport(args[2], report);
                return report.ErrorCount == 0 ? 0 : 1;
            }
            catch (Exception error)
            {
                WriteReport(args[2], new BenchmarkReport
                {
                    FormatId = "amvision.workflow-trigger-transport-benchmark.v1",
                    Transport = config?.Transport ?? string.Empty,
                    InputMode = config?.InputMode ?? string.Empty,
                    ErrorCount = 1,
                    Errors = new[] { FormatError(error) }
                });
                return 1;
            }
        }

        private static BenchmarkReport Execute(BenchmarkConfig config)
        {
            var inputSizeBytes = new FileInfo(config.InputPath).Length;
            var input = string.Equals(config.InputMode, "encoded-file", StringComparison.Ordinal)
                ? Array.Empty<byte>()
                : File.ReadAllBytes(config.InputPath);
            var base64 = string.Equals(config.InputMode, "base64", StringComparison.Ordinal)
                ? "data:" + config.MediaType + ";base64," + Convert.ToBase64String(input)
                : string.Empty;
            var latencies = new List<double>(config.Iterations);
            var transportOverheads = new List<double>(config.Iterations);
            var gcCollectionSamples = new List<GcCollectionSample>();
            var timingTotals = new TimingTotals();
            using (var invocation = CreateInvocation(config, input, base64))
            {
                for (var index = 0; index < config.WarmupIterations; index += 1)
                {
                    invocation.Invoke(index, collectTimings: false, timingTotals);
                }

                GC.Collect();
                GC.WaitForPendingFinalizers();
                GC.Collect();
                var managedBefore = GC.GetTotalMemory(forceFullCollection: false);
                var collectionsBefore = new[]
                {
                    GC.CollectionCount(0),
                    GC.CollectionCount(1),
                    GC.CollectionCount(2)
                };
                for (var index = 0; index < config.Iterations; index += 1)
                {
                    var requestCollectionsBefore = new[]
                    {
                        GC.CollectionCount(0),
                        GC.CollectionCount(1),
                        GC.CollectionCount(2)
                    };
                    var startedAt = Stopwatch.GetTimestamp();
                    var runtimeInvokeMs = invocation.Invoke(
                        index + config.WarmupIterations,
                        config.EnableTimings,
                        timingTotals);
                    var latencyMs = ElapsedMilliseconds(startedAt);
                    latencies.Add(latencyMs);
                    if (runtimeInvokeMs >= 0)
                    {
                        transportOverheads.Add(Math.Max(0.0, latencyMs - runtimeInvokeMs));
                    }

                    var gen0Delta = GC.CollectionCount(0) - requestCollectionsBefore[0];
                    var gen1Delta = GC.CollectionCount(1) - requestCollectionsBefore[1];
                    var gen2Delta = GC.CollectionCount(2) - requestCollectionsBefore[2];
                    if (gen0Delta > 0 || gen1Delta > 0 || gen2Delta > 0)
                    {
                        gcCollectionSamples.Add(new GcCollectionSample
                        {
                            RequestIndex = index,
                            LatencyMs = latencyMs,
                            Gen0Collections = gen0Delta,
                            Gen1Collections = gen1Delta,
                            Gen2Collections = gen2Delta
                        });
                    }
                }

                var managedAfter = GC.GetTotalMemory(forceFullCollection: false);
                using (var process = Process.GetCurrentProcess())
                {
                    return new BenchmarkReport
                    {
                        FormatId = "amvision.workflow-trigger-transport-benchmark.v1",
                        Transport = config.Transport,
                        InputMode = config.InputMode,
                        InputSizeBytes = inputSizeBytes,
                        Width = config.Width,
                        Height = config.Height,
                        WarmupIterations = config.WarmupIterations,
                        Iterations = config.Iterations,
                        SuccessCount = config.Iterations,
                        ErrorCount = 0,
                        LatencyMs = Distribution.From(latencies),
                        LatencySamplesMs = latencies,
                        TransportOverheadMs = transportOverheads.Count == latencies.Count
                            ? Distribution.From(transportOverheads)
                            : null,
                        TransportOverheadSamplesMs = transportOverheads,
                        AverageSdkTimings = timingTotals.ToAverages(config.EnableTimings ? config.Iterations : 0),
                        TimingDistributionsMs = timingTotals.ToDistributions(
                            config.EnableTimings ? config.Iterations : 0),
                        TimingSamplesMs = timingTotals.ToSamples(
                            config.EnableTimings ? config.Iterations : 0),
                        ManagedHeapBeforeBytes = managedBefore,
                        ManagedHeapAfterBytes = managedAfter,
                        ManagedHeapDeltaBytes = managedAfter - managedBefore,
                        PeakWorkingSetBytes = process.PeakWorkingSet64,
                        Gen0Collections = GC.CollectionCount(0) - collectionsBefore[0],
                        Gen1Collections = GC.CollectionCount(1) - collectionsBefore[1],
                        Gen2Collections = GC.CollectionCount(2) - collectionsBefore[2],
                        GcCollectionSamples = gcCollectionSamples,
                        Errors = Array.Empty<string>()
                    };
                }
            }
        }

        private static IBenchmarkInvocation CreateInvocation(
            BenchmarkConfig config,
            byte[] input,
            string base64)
        {
            if (string.Equals(config.Transport, "local-shared-memory", StringComparison.Ordinal))
            {
                return new SharedMemoryInvocation(config, input, base64);
            }

            if (string.Equals(config.Transport, "zeromq-topic", StringComparison.Ordinal))
            {
                return new ZeroMqInvocation(config, input, base64);
            }

            throw new ArgumentException("Unsupported benchmark transport.");
        }

        private static double ElapsedMilliseconds(long startedAt)
        {
            return (Stopwatch.GetTimestamp() - startedAt) * 1000.0 / Stopwatch.Frequency;
        }

        private static string FormatError(Exception error)
        {
            return error.GetType().FullName + ": " + error.Message;
        }

        private static void WriteReport(string outputPath, BenchmarkReport report)
        {
            var fullPath = Path.GetFullPath(outputPath);
            Directory.CreateDirectory(Path.GetDirectoryName(fullPath) ?? ".");
            File.WriteAllText(fullPath, JsonConvert.SerializeObject(report, Formatting.Indented));
        }

        private interface IBenchmarkInvocation : IDisposable
        {
            double Invoke(int sequence, bool collectTimings, TimingTotals totals);
        }

        private sealed class SharedMemoryInvocation : IBenchmarkInvocation
        {
            private readonly BenchmarkConfig config;
            private readonly byte[] input;
            private readonly string base64;
            private readonly SharedMemoryTriggerClient client;

            internal SharedMemoryInvocation(BenchmarkConfig config, byte[] input, string base64)
            {
                this.config = config;
                this.input = input;
                this.base64 = base64;
                var buffersRoot = Path.GetFullPath(config.BuffersRoot);
                client = new SharedMemoryTriggerClient(new SharedMemoryTriggerClientOptions
                {
                    BuffersRoot = buffersRoot,
                    TriggerSourceId = config.TriggerSourceId,
                    RouteGeneration = config.RouteGeneration,
                    DefaultInputBinding = config.InputBinding,
                    Timeout = TimeSpan.FromSeconds(config.TimeoutSeconds)
                });
            }

            public double Invoke(int sequence, bool collectTimings, TimingTotals totals)
            {
                var request = new SharedMemoryTriggerRequest
                {
                    EventId = "benchmark-shared-" + sequence.ToString(CultureInfo.InvariantCulture) + "-" + Guid.NewGuid().ToString("N"),
                    TraceId = "benchmark-shared-" + Guid.NewGuid().ToString("N"),
                    EnableTimings = collectTimings
                };
                SharedMemoryTriggerTimings? timings;
                var runtimeInvokeMs = -1.0;
                using (var result = InvokeByMode(request))
                {
                    if (!string.Equals(result.Result.State, "succeeded", StringComparison.OrdinalIgnoreCase))
                    {
                        throw new InvalidOperationException("Shared-memory Workflow result did not succeed.");
                    }

                    timings = result.Timings;
                    if (collectTimings)
                    {
                        totals.AddBackend(result.Result.Metadata);
                        runtimeInvokeMs = ReadRuntimeInvokeMs(result.Result.Metadata);
                    }
                }

                if (timings != null)
                {
                    totals.Add(timings);
                }

                return runtimeInvokeMs;
            }

            public void Dispose()
            {
                client.Dispose();
            }

            private SharedMemoryTriggerResult InvokeByMode(SharedMemoryTriggerRequest request)
            {
                switch (config.InputMode)
                {
                    case "bgr24":
                        return client.InvokeBgr24(input, config.Width, config.Height, request);
                    case "bgr24-direct":
                        return client.InvokeBgr24(
                            config.Width,
                            config.Height,
                            destination => input.AsSpan().CopyTo(destination),
                            request);
                    case "encoded-bytes":
                        return client.InvokeImageBytes(input, config.MediaType, request);
                    case "encoded-file":
                        return client.InvokeImageFromFile(config.InputPath, config.MediaType, request);
                    case "base64":
                        return client.InvokeImageBase64(base64, config.MediaType, request);
                    default:
                        throw new ArgumentException("Unsupported shared-memory input mode.");
                }
            }
        }

        private sealed class ZeroMqInvocation : IBenchmarkInvocation
        {
            private readonly BenchmarkConfig config;
            private readonly byte[] input;
            private readonly string base64;
            private readonly AMVisionTriggerClient client;

            internal ZeroMqInvocation(BenchmarkConfig config, byte[] input, string base64)
            {
                this.config = config;
                this.input = input;
                this.base64 = base64;
                client = new AMVisionTriggerClient(new AMVisionTriggerClientOptions
                {
                    Endpoint = config.Endpoint,
                    TriggerSourceId = config.TriggerSourceId,
                    DefaultInputBinding = config.InputBinding,
                    Timeout = TimeSpan.FromSeconds(config.TimeoutSeconds)
                });
            }

            public double Invoke(int sequence, bool collectTimings, TimingTotals totals)
            {
                _ = collectTimings;
                _ = totals;
                var request = BuildRequest();
                request.EventId = "benchmark-zmq-" + sequence.ToString(CultureInfo.InvariantCulture) + "-" + Guid.NewGuid().ToString("N");
                request.TraceId = "benchmark-zmq-" + Guid.NewGuid().ToString("N");
                var result = client.InvokeImage(request);
                if (!string.Equals(result.State, "succeeded", StringComparison.OrdinalIgnoreCase))
                {
                    throw new InvalidOperationException("ZeroMQ Workflow result did not succeed.");
                }

                if (collectTimings)
                {
                    totals.AddBackend(result.Metadata);
                    return ReadRuntimeInvokeMs(result.Metadata);
                }

                return -1.0;
            }

            public void Dispose()
            {
                client.Dispose();
            }

            private ImageTriggerRequest BuildRequest()
            {
                switch (config.InputMode)
                {
                    case "bgr24":
                        return ImageTriggerRequest.FromBgr24(input, config.Width, config.Height);
                    case "encoded-bytes":
                        return ImageTriggerRequest.FromBytes(input, config.MediaType);
                    case "encoded-file":
                        return ImageTriggerRequest.FromFile(config.InputPath, config.MediaType);
                    case "base64":
                        return ImageTriggerRequest.FromBase64(base64, config.MediaType);
                    default:
                        throw new ArgumentException("Unsupported ZeroMQ input mode.");
                }
            }
        }

        private sealed class BenchmarkConfig
        {
            [JsonProperty("transport")]
            public string Transport { get; set; } = string.Empty;

            [JsonProperty("buffers_root")]
            public string BuffersRoot { get; set; } = string.Empty;

            [JsonProperty("endpoint")]
            public string Endpoint { get; set; } = string.Empty;

            [JsonProperty("trigger_source_id")]
            public string TriggerSourceId { get; set; } = string.Empty;

            [JsonProperty("route_generation")]
            public long RouteGeneration { get; set; }

            [JsonProperty("input_binding")]
            public string InputBinding { get; set; } = "request_image_ref";

            [JsonProperty("input_mode")]
            public string InputMode { get; set; } = string.Empty;

            [JsonProperty("input_path")]
            public string InputPath { get; set; } = string.Empty;

            [JsonProperty("media_type")]
            public string MediaType { get; set; } = "application/octet-stream";

            [JsonProperty("width")]
            public int Width { get; set; }

            [JsonProperty("height")]
            public int Height { get; set; }

            [JsonProperty("warmup_iterations")]
            public int WarmupIterations { get; set; }

            [JsonProperty("iterations")]
            public int Iterations { get; set; }

            [JsonProperty("timeout_seconds")]
            public double TimeoutSeconds { get; set; } = 30;

            [JsonProperty("enable_timings")]
            public bool EnableTimings { get; set; }

            internal void Validate()
            {
                if (string.IsNullOrWhiteSpace(Transport)
                    || string.IsNullOrWhiteSpace(TriggerSourceId)
                    || string.IsNullOrWhiteSpace(InputMode)
                    || string.IsNullOrWhiteSpace(InputPath)
                    || !File.Exists(InputPath))
                {
                    throw new ArgumentException("Benchmark transport, source, mode and input file are required.");
                }

                if (WarmupIterations < 0 || Iterations <= 0 || TimeoutSeconds <= 0)
                {
                    throw new ArgumentOutOfRangeException(nameof(Iterations));
                }

                if ((InputMode == "bgr24" || InputMode == "bgr24-direct")
                    && (Width <= 0 || Height <= 0))
                {
                    throw new ArgumentException("Raw BGR24 benchmark requires width and height.");
                }

                if (Transport == "local-shared-memory"
                    && (string.IsNullOrWhiteSpace(BuffersRoot) || RouteGeneration <= 0))
                {
                    throw new ArgumentException("Shared-memory benchmark requires buffers_root and route_generation.");
                }

                if (Transport == "zeromq-topic" && string.IsNullOrWhiteSpace(Endpoint))
                {
                    throw new ArgumentException("ZeroMQ benchmark requires endpoint.");
                }
            }
        }

        private sealed class BenchmarkReport
        {
            [JsonProperty("format_id")]
            public string FormatId { get; set; } = string.Empty;

            [JsonProperty("transport")]
            public string Transport { get; set; } = string.Empty;

            [JsonProperty("input_mode")]
            public string InputMode { get; set; } = string.Empty;

            [JsonProperty("input_size_bytes")]
            public long InputSizeBytes { get; set; }

            [JsonProperty("width")]
            public int Width { get; set; }

            [JsonProperty("height")]
            public int Height { get; set; }

            [JsonProperty("warmup_iterations")]
            public int WarmupIterations { get; set; }

            [JsonProperty("iterations")]
            public int Iterations { get; set; }

            [JsonProperty("success_count")]
            public int SuccessCount { get; set; }

            [JsonProperty("error_count")]
            public int ErrorCount { get; set; }

            [JsonProperty("latency_ms")]
            public Distribution? LatencyMs { get; set; }

            [JsonProperty("latency_samples_ms")]
            public IReadOnlyList<double> LatencySamplesMs { get; set; } = Array.Empty<double>();

            [JsonProperty("transport_overhead_ms")]
            public Distribution? TransportOverheadMs { get; set; }

            [JsonProperty("transport_overhead_samples_ms")]
            public IReadOnlyList<double> TransportOverheadSamplesMs { get; set; } = Array.Empty<double>();

            [JsonProperty("average_sdk_timings_ms")]
            public IDictionary<string, double> AverageSdkTimings { get; set; } = new Dictionary<string, double>();

            [JsonProperty("timing_distributions_ms")]
            public IDictionary<string, Distribution> TimingDistributionsMs { get; set; } = new Dictionary<string, Distribution>();

            [JsonProperty("timing_samples_ms")]
            public IDictionary<string, IReadOnlyList<double>> TimingSamplesMs { get; set; } = new Dictionary<string, IReadOnlyList<double>>();

            [JsonProperty("managed_heap_before_bytes")]
            public long ManagedHeapBeforeBytes { get; set; }

            [JsonProperty("managed_heap_after_bytes")]
            public long ManagedHeapAfterBytes { get; set; }

            [JsonProperty("managed_heap_delta_bytes")]
            public long ManagedHeapDeltaBytes { get; set; }

            [JsonProperty("peak_working_set_bytes")]
            public long PeakWorkingSetBytes { get; set; }

            [JsonProperty("gen0_collections")]
            public int Gen0Collections { get; set; }

            [JsonProperty("gen1_collections")]
            public int Gen1Collections { get; set; }

            [JsonProperty("gen2_collections")]
            public int Gen2Collections { get; set; }

            [JsonProperty("gc_collection_samples")]
            public IReadOnlyList<GcCollectionSample> GcCollectionSamples { get; set; } = Array.Empty<GcCollectionSample>();

            [JsonProperty("errors")]
            public IReadOnlyList<string> Errors { get; set; } = Array.Empty<string>();
        }

        private sealed class GcCollectionSample
        {
            [JsonProperty("request_index")]
            public int RequestIndex { get; set; }

            [JsonProperty("latency_ms")]
            public double LatencyMs { get; set; }

            [JsonProperty("gen0_collections")]
            public int Gen0Collections { get; set; }

            [JsonProperty("gen1_collections")]
            public int Gen1Collections { get; set; }

            [JsonProperty("gen2_collections")]
            public int Gen2Collections { get; set; }
        }

        private sealed class Distribution
        {
            [JsonProperty("min")]
            public double Min { get; set; }

            [JsonProperty("mean")]
            public double Mean { get; set; }

            [JsonProperty("p50")]
            public double P50 { get; set; }

            [JsonProperty("p95")]
            public double P95 { get; set; }

            [JsonProperty("p99")]
            public double P99 { get; set; }

            [JsonProperty("max")]
            public double Max { get; set; }

            internal static Distribution From(IReadOnlyList<double> values)
            {
                var ordered = values.OrderBy(item => item).ToArray();
                return new Distribution
                {
                    Min = Round(ordered[0]),
                    Mean = Round(ordered.Average()),
                    P50 = Round(Percentile(ordered, 0.50)),
                    P95 = Round(Percentile(ordered, 0.95)),
                    P99 = Round(Percentile(ordered, 0.99)),
                    Max = Round(ordered[ordered.Length - 1])
                };
            }

            private static double Percentile(IReadOnlyList<double> ordered, double quantile)
            {
                var position = (ordered.Count - 1) * quantile;
                var lower = (int)Math.Floor(position);
                var upper = (int)Math.Ceiling(position);
                if (lower == upper)
                {
                    return ordered[lower];
                }

                return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower);
            }

            private static double Round(double value)
            {
                return Math.Round(value, 6, MidpointRounding.AwayFromZero);
            }
        }

        private sealed class TimingTotals
        {
            private double convert;
            private double base64;
            private double mailboxClaim;
            private double allocationWait;
            private double writerOpen;
            private double write;
            private double writerClose;
            private double checksum;
            private double requestPublish;
            private double responseWait;
            private double resultBuild;
            private double invoke;
            private double attachment;
            private double dispose;
            private readonly Dictionary<string, double> backend = new Dictionary<string, double>(StringComparer.Ordinal);
            private readonly Dictionary<string, List<double>> samples = new Dictionary<string, List<double>>(StringComparer.Ordinal);

            internal void Add(SharedMemoryTriggerTimings timings)
            {
                convert += timings.SdkConvertToBgr24Ms;
                base64 += timings.SdkBase64DecodeMs;
                mailboxClaim += timings.SdkMailboxClaimMs;
                allocationWait += timings.SdkAllocationWaitMs;
                writerOpen += timings.SdkWriterOpenMs;
                write += timings.SdkWriteLocalBufferMs;
                writerClose += timings.SdkWriterCloseMs;
                checksum += timings.SdkChecksumMs;
                requestPublish += timings.SdkRequestPublishMs;
                responseWait += timings.SdkResponseWaitMs;
                resultBuild += timings.SdkResultBuildMs;
                invoke += timings.InvokeReturnMs;
                attachment += timings.AttachmentAccessMs;
                dispose += timings.DisposeAckMs;
                AddSample("sdk_convert_to_bgr24_ms", timings.SdkConvertToBgr24Ms);
                AddSample("sdk_base64_decode_ms", timings.SdkBase64DecodeMs);
                AddSample("sdk_mailbox_claim_ms", timings.SdkMailboxClaimMs);
                AddSample("sdk_allocation_wait_ms", timings.SdkAllocationWaitMs);
                AddSample("sdk_writer_open_ms", timings.SdkWriterOpenMs);
                AddSample("sdk_write_local_buffer_ms", timings.SdkWriteLocalBufferMs);
                AddSample("sdk_writer_close_ms", timings.SdkWriterCloseMs);
                AddSample("sdk_checksum_ms", timings.SdkChecksumMs);
                AddSample("sdk_request_publish_ms", timings.SdkRequestPublishMs);
                AddSample("sdk_response_wait_ms", timings.SdkResponseWaitMs);
                AddSample("sdk_result_build_ms", timings.SdkResultBuildMs);
                AddSample("invoke_return_ms", timings.InvokeReturnMs);
                AddSample("attachment_access_ms", timings.AttachmentAccessMs);
                AddSample("dispose_ack_ms", timings.DisposeAckMs);
            }

            internal void AddBackend(IDictionary<string, JToken> metadata)
            {
                JToken? timingToken;
                if (!metadata.TryGetValue("timings", out timingToken) || !(timingToken is JObject timings))
                {
                    return;
                }

                foreach (var property in timings.Properties())
                {
                    if (property.Value.Type != JTokenType.Integer && property.Value.Type != JTokenType.Float)
                    {
                        continue;
                    }

                    var key = "backend_" + property.Name;
                    var value = property.Value.Value<double>();
                    backend[key] = backend.TryGetValue(key, out var current)
                        ? current + value
                        : value;
                    AddSample(key, value);
                }
            }

            internal IDictionary<string, double> ToAverages(int count)
            {
                if (count <= 0)
                {
                    return new Dictionary<string, double>();
                }

                var averages = new Dictionary<string, double>
                {
                    ["sdk_convert_to_bgr24_ms"] = convert / count,
                    ["sdk_base64_decode_ms"] = base64 / count,
                    ["sdk_mailbox_claim_ms"] = mailboxClaim / count,
                    ["sdk_allocation_wait_ms"] = allocationWait / count,
                    ["sdk_writer_open_ms"] = writerOpen / count,
                    ["sdk_write_local_buffer_ms"] = write / count,
                    ["sdk_writer_close_ms"] = writerClose / count,
                    ["sdk_checksum_ms"] = checksum / count,
                    ["sdk_request_publish_ms"] = requestPublish / count,
                    ["sdk_response_wait_ms"] = responseWait / count,
                    ["sdk_result_build_ms"] = resultBuild / count,
                    ["invoke_return_ms"] = invoke / count,
                    ["attachment_access_ms"] = attachment / count,
                    ["dispose_ack_ms"] = dispose / count
                };
                foreach (var item in backend)
                {
                    averages[item.Key] = item.Value / count;
                }

                return averages;
            }

            internal IDictionary<string, Distribution> ToDistributions(int count)
            {
                if (count <= 0)
                {
                    return new Dictionary<string, Distribution>();
                }

                return samples
                    .Where(item => item.Value.Count == count)
                    .ToDictionary(
                        item => item.Key,
                        item => Distribution.From(item.Value),
                    StringComparer.Ordinal);
            }

            internal IDictionary<string, IReadOnlyList<double>> ToSamples(int count)
            {
                if (count <= 0)
                {
                    return new Dictionary<string, IReadOnlyList<double>>();
                }

                return samples
                    .Where(item => item.Value.Count == count)
                    .ToDictionary(
                        item => item.Key,
                        item => (IReadOnlyList<double>)item.Value.ToArray(),
                        StringComparer.Ordinal);
            }

            private void AddSample(string key, double value)
            {
                if (!samples.TryGetValue(key, out var values))
                {
                    values = new List<double>();
                    samples[key] = values;
                }

                values.Add(value);
            }
        }

        private static double ReadRuntimeInvokeMs(IDictionary<string, JToken> metadata)
        {
            JToken? timingToken;
            if (!metadata.TryGetValue("timings", out timingToken) || !(timingToken is JObject timings))
            {
                return -1.0;
            }

            var runtimeInvoke = timings["workflow_runtime_invoke_ms"]
                ?? timings["trigger_runtime_submit_ms"];
            return runtimeInvoke != null
                && (runtimeInvoke.Type == JTokenType.Integer || runtimeInvoke.Type == JTokenType.Float)
                ? Math.Max(0.0, runtimeInvoke.Value<double>())
                : -1.0;
        }
    }
}
