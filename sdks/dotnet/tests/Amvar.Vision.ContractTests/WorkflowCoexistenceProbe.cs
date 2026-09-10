using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using Amvar.Vision;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

namespace Amvar.Vision.ContractTests
{
    /// <summary>复用 SDK client 检查真实 Runtime/Trigger 耗时、结果及请求身份；不修改服务资源。</summary>
    internal static class WorkflowCoexistenceProbe
    {
        internal static int Run(string[] args)
        {
            if (args.Length != 3) return 64;
            var samples = new List<object>();
            try
            {
                var config = JObject.Parse(File.ReadAllText(args[1]));
                var mode = (string?)config["mode"] ?? "";
                if (mode != "runtime" && mode != "zeromq") throw new ArgumentException("Unsupported mode: " + mode);
                var image = File.ReadAllBytes((string?)config["image"] ?? "");
                var iterations = (int?)config["iterations"] ?? 1;
                var warmup = (int?)config["warmup"] ?? 0;
                if (iterations <= 0 || warmup < 0) throw new ArgumentException("Invalid iteration count.");
                var payload = config["payload"] as JObject ?? new JObject();
                var ids = new HashSet<string>(StringComparer.Ordinal);
                using (var http = mode == "runtime" ? new AMVisionClient(new AMVisionClientOptions
                {
                    BaseApiUrl = (string?)config["base_url"] ?? "http://127.0.0.1:5600",
                    AccessToken = Environment.GetEnvironmentVariable("AMVISION_AUDIT_TOKEN") ?? "unused",
                    Timeout = TimeSpan.FromSeconds(60)
                }) : null)
                using (var trigger = mode == "zeromq" ? new AMVisionTriggerClient(new AMVisionTriggerClientOptions
                {
                    Endpoint = (string?)config["endpoint"] ?? "tcp://127.0.0.1:5555",
                    TriggerSourceId = (string?)config["source_id"] ?? "unused",
                    DefaultInputBinding = "request_image_ref",
                    Timeout = TimeSpan.FromSeconds(60)
                }) : null)
                {
                    for (var index = -warmup; index < iterations; index++)
                    {
                        var startedAt = DateTimeOffset.UtcNow;
                        var clock = Stopwatch.StartNew();
                        string state, runId;
                        JToken result;
                        JToken metadata = new JObject();
                        if (mode == "runtime")
                        {
                            var request = new WorkflowRuntimeMultipartInvokeRequest { TimeoutSeconds = 60 };
                            request.Files.Add(WorkflowRuntimeMultipartFile.FromBytes("request_image_ref", image, "fixture.bmp", "image/bmp"));
                            foreach (var property in payload.Properties()) request.InputBindings[property.Name] = property.Value.DeepClone();
                            request.ExecutionMetadata["workflow_run_record_mode"] = "none";
                            request.ExecutionMetadata["retain_trace_enabled"] = false;
                            request.ExecutionMetadata["retain_node_records_enabled"] = false;
                            var response = http!.InvokeWorkflowAppRuntimeUploadAppResultResponseAsync(
                                (string?)config["runtime_id"] ?? "", request).GetAwaiter().GetResult();
                            state = response.State;
                            runId = response.WorkflowRunId;
                            result = response.Results;
                        }
                        else if (mode == "zeromq")
                        {
                            var request = (string?)config["input_mode"] == "bgr24"
                                ? ImageTriggerRequest.FromBgr24(image, (int)config["width"]!, (int)config["height"]!)
                                : ImageTriggerRequest.FromBytes(image, "image/bmp");
                            request.EventId = "coexistence-" + Guid.NewGuid().ToString("N");
                            foreach (var property in payload.Properties()) request.Payload[property.Name] = property.Value.DeepClone();
                            var response = trigger!.InvokeImage(request);
                            if (response.EventId != request.EventId || response.TriggerSourceId != (string?)config["source_id"])
                                throw new InvalidDataException("Trigger event identity mismatch.");
                            state = response.State;
                            runId = response.WorkflowRunId ?? "";
                            var envelope = JObject.FromObject(response.ResponsePayload);
                            if ((string?)envelope["workflow_run_id"] != runId)
                                throw new InvalidDataException("Trigger result run identity mismatch.");
                            result = envelope["results"] ?? throw new InvalidDataException("Missing trigger results.");
                            metadata = JObject.FromObject(response.Metadata);
                        }
                        else throw new ArgumentException("Unsupported mode: " + mode);
                        clock.Stop();
                        if (state != "succeeded" || string.IsNullOrEmpty(runId) || !ids.Add(runId))
                            throw new InvalidDataException("Workflow state or run identity invalid: " + state);
                        // 先保留证据再校验业务值，期望值不匹配时保留实际响应。
                        samples.Add(new { index, started_at = startedAt, elapsed_ms = clock.Elapsed.TotalMilliseconds, run_id = runId, state, result, metadata });
                        if (config["expected"] is JObject expected)
                        {
                            foreach (var item in expected.Properties())
                            {
                                var actual = result.SelectToken(item.Name);
                                if (!JToken.DeepEquals(actual, item.Value))
                                    throw new InvalidDataException("Unexpected business result at " + item.Name);
                            }
                        }
                    }
                }
                using (var process = Process.GetCurrentProcess())
                {
                    File.WriteAllText(args[2], JsonConvert.SerializeObject(new
                    {
                        passed = true, mode, iterations, warmup, samples,
                        peak_working_set_bytes = process.PeakWorkingSet64,
                        managed_heap_bytes = GC.GetTotalMemory(false)
                    }, Formatting.Indented));
                }
                return 0;
            }
            catch (Exception error)
            {
                File.WriteAllText(args[2], JsonConvert.SerializeObject(new
                { passed = false, error = error.ToString(), samples }, Formatting.Indented));
                return 1;
            }
        }
    }
}
