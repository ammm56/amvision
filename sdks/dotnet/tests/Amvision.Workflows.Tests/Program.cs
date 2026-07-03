using System.Net;
using System.Net.Http;
using System.Net.Sockets;
using System.Text;
using System.Text.Json;
using NetMQ;
using NetMQ.Sockets;
using Amvision.Workflows;

var tests = new Action[]
{
    InvokeImageBuildsExpectedEnvelope,
    ImageTriggerRequestHelpersBuildSecondFrameBytes,
    InvokeImageUsesNetMqReqRepTransport,
    ErrorReplyRaisesTypedException,
    InvalidImageRequestIsRejected,
    EmptyReplyIsRejected,
    TimeoutExceptionIsPropagated,
    WorkflowRuntimeImageInvokeBuildsExpectedHttpRequest,
    WorkflowRuntimeInvokeSupportsDirectInputJson,
    WorkflowRuntimeRunAndLifecycleEndpointsUseExpectedHttpRequests,
    TriggerSourceCreateListDeleteUsesExpectedHttpRequests,
    TypedResponsesDeserializeWorkflowResponses,
    TriggerSourceHealthUsesExpectedHttpEndpoint,
    WorkflowApiResponseParsesBackendErrorEnvelope,
    ZeroMqEnvelopeAddsHelperPayload,
    SchemaFixtureMatchesGeneratedEnvelope,
    BackendLocalSmokeTest
};

foreach (var test in tests)
{
    test();
    Console.WriteLine($"passed: {test.Method.Name}");
}

NetMQConfig.Cleanup(block: false);

// 验证文件、base64 和 stream helper 最终仍走 multipart 第二帧 bytes。
static void ImageTriggerRequestHelpersBuildSecondFrameBytes()
{
    var fromBase64 = ImageTriggerRequest.FromBase64("data:image/png;base64,AQID");
    AssertEqual("image/png", fromBase64.MediaType);
    AssertSequence(new byte[] { 1, 2, 3 }, fromBase64.ImageBytes);

    using var stream = new MemoryStream(new byte[] { 4, 5, 6 });
    var fromStream = ImageTriggerRequest.FromStream(stream, "image/jpeg");
    AssertEqual("image/jpeg", fromStream.MediaType);
    AssertSequence(new byte[] { 4, 5, 6 }, fromStream.ImageBytes);

    var tempPath = Path.Combine(Path.GetTempPath(), $"amvision-sdk-{Guid.NewGuid():N}.jpg");
    try
    {
        File.WriteAllBytes(tempPath, new byte[] { 7, 8, 9 });
        var fromFile = ImageTriggerRequest.FromFile(tempPath);
        AssertEqual("image/jpeg", fromFile.MediaType);
        AssertSequence(new byte[] { 7, 8, 9 }, fromFile.ImageBytes);
    }
    finally
    {
        if (File.Exists(tempPath))
        {
            File.Delete(tempPath);
        }
    }

    var transport = new FakeTransport(
        "{\"format_id\":\"amvision.workflow-trigger-result.v1\",\"trigger_source_id\":\"trigger-source-helper\",\"event_id\":\"event-helper\",\"state\":\"accepted\",\"workflow_run_id\":\"workflow-run-helper\",\"response_payload\":{},\"metadata\":{}}"
    );
    using var client = new AmvisionTriggerClient(
        new AmvisionTriggerClientOptions
        {
            TriggerSourceId = "trigger-source-helper"
        },
        transport
    );

    _ = client.InvokeImage(fromBase64);

    AssertEqual(2, transport.LastFrames.Count);
    AssertSequence(new byte[] { 1, 2, 3 }, transport.LastFrames[1]);
    using var document = JsonDocument.Parse(Encoding.UTF8.GetString(transport.LastFrames[0]));
    AssertEqual("request_image_ref", document.RootElement.GetProperty("input_binding").GetString());
    AssertEqual(false, document.RootElement.GetProperty("payload").TryGetProperty("request_image_base64", out _));
}

// 验证 SDK 可以构造 backend-service 兼容的 envelope。
static void InvokeImageBuildsExpectedEnvelope()
{
    var transport = new FakeTransport(
        "{\"format_id\":\"amvision.workflow-trigger-result.v1\",\"trigger_source_id\":\"trigger-source-04\",\"event_id\":\"event-1\",\"state\":\"accepted\",\"workflow_run_id\":\"workflow-run-1\",\"response_payload\":{},\"metadata\":{}}"
    );
    using var client = new AmvisionTriggerClient(
        new AmvisionTriggerClientOptions
        {
            TriggerSourceId = "trigger-source-04",
            Timeout = TimeSpan.FromSeconds(1)
        },
        transport
    );

    var result = client.InvokeImage(new ImageTriggerRequest
    {
        ImageBytes = new byte[] { 1, 2, 3 },
        EventId = "event-1",
        TraceId = "trace-1",
        MediaType = "image/jpeg",
        Shape = new[] { 2, 2, 3 },
        DType = "uint8",
        Layout = "HWC",
        PixelFormat = "BGR",
        Metadata = { ["line_id"] = "line-a" },
        Payload = { ["job_id"] = "job-1" }
    });

    AssertEqual("accepted", result.State);
    AssertEqual("workflow-run-1", result.WorkflowRunId);
    AssertEqual(2, transport.LastFrames.Count);
    AssertSequence(new byte[] { 1, 2, 3 }, transport.LastFrames[1]);

    using var document = JsonDocument.Parse(Encoding.UTF8.GetString(transport.LastFrames[0]));
    var root = document.RootElement;
    AssertEqual("trigger-source-04", root.GetProperty("trigger_source_id").GetString());
    AssertEqual("event-1", root.GetProperty("event_id").GetString());
    AssertEqual("trace-1", root.GetProperty("trace_id").GetString());
    AssertEqual("request_image_ref", root.GetProperty("input_binding").GetString());
    AssertEqual("image/jpeg", root.GetProperty("media_type").GetString());
    AssertEqual("line-a", root.GetProperty("metadata").GetProperty("line_id").GetString());
    AssertEqual("job-1", root.GetProperty("payload").GetProperty("job_id").GetString());
    AssertEqual(2, root.GetProperty("shape")[0].GetInt32());
}

// 验证 NetMQ REQ/REP transport 可以完成真实 socket 往返。
static void InvokeImageUsesNetMqReqRepTransport()
{
    var endpoint = $"tcp://127.0.0.1:{GetFreeTcpPort()}";
    var ready = new ManualResetEventSlim(false);
    Exception? serverException = null;
    IReadOnlyList<byte[]> receivedFrames = Array.Empty<byte[]>();
    var thread = new Thread(() =>
    {
        try
        {
            using var socket = new ResponseSocket();
            socket.Options.Linger = TimeSpan.Zero;
            socket.Bind(endpoint);
            ready.Set();

            var request = new NetMQMessage();
            if (!socket.TryReceiveMultipartMessage(TimeSpan.FromSeconds(5), ref request))
            {
                throw new TimeoutException("Timed out waiting for SDK request.");
            }

            receivedFrames = request.Select(frame => frame.ToByteArray()).ToArray();
            socket.SendFrame("{\"format_id\":\"amvision.workflow-trigger-result.v1\",\"trigger_source_id\":\"trigger-source-netmq\",\"event_id\":\"event-netmq\",\"state\":\"accepted\",\"workflow_run_id\":\"workflow-run-netmq\",\"response_payload\":{},\"metadata\":{}}");
        }
        catch (Exception exception)
        {
            serverException = exception;
            ready.Set();
        }
    });
    thread.IsBackground = true;
    thread.Start();
    ready.Wait(TimeSpan.FromSeconds(5));

    using var client = new AmvisionTriggerClient(new AmvisionTriggerClientOptions
    {
        Endpoint = endpoint,
        TriggerSourceId = "trigger-source-netmq",
        Timeout = TimeSpan.FromSeconds(5)
    });

    var result = client.InvokeImage(new ImageTriggerRequest
    {
        ImageBytes = new byte[] { 9, 8, 7 },
        EventId = "event-netmq",
        MediaType = "image/png"
    });

    thread.Join(TimeSpan.FromSeconds(5));
    if (serverException is not null)
    {
        throw serverException;
    }

    AssertEqual("accepted", result.State);
    AssertEqual("workflow-run-netmq", result.WorkflowRunId);
    AssertEqual(2, receivedFrames.Count);
    AssertSequence(new byte[] { 9, 8, 7 }, receivedFrames[1]);
}

// 验证 ZeroMQ error reply 会转换为 SDK 异常。
static void ErrorReplyRaisesTypedException()
{
    var transport = new FakeTransport(
        "{\"format_id\":\"amvision.zeromq-trigger-error.v1\",\"trigger_source_id\":\"trigger-source-04\",\"state\":\"failed\",\"error_code\":\"invalid_request\",\"error_message\":\"bad request\",\"details\":{\"field\":\"media_type\"}}"
    );
    using var client = new AmvisionTriggerClient(
        new AmvisionTriggerClientOptions { TriggerSourceId = "trigger-source-04" },
        transport
    );

    var exception = AssertThrows<AmvisionTriggerException>(() => client.InvokeImage(new ImageTriggerRequest
    {
        ImageBytes = new byte[] { 1 }
    }));
    AssertEqual("invalid_request", exception.ErrorCode);
    AssertEqual("bad request", exception.Message);
}

// 验证空图片请求会在本地被拒绝。
static void InvalidImageRequestIsRejected()
{
    using var client = new AmvisionTriggerClient(
        new AmvisionTriggerClientOptions { TriggerSourceId = "trigger-source-04" },
        new FakeTransport("{}")
    );

    AssertThrows<ArgumentException>(() => client.InvokeImage(new ImageTriggerRequest()));
}

// 验证空 reply 会转换为 invalid_reply 异常。
static void EmptyReplyIsRejected()
{
    using var client = new AmvisionTriggerClient(
        new AmvisionTriggerClientOptions { TriggerSourceId = "trigger-source-04" },
        new FakeTransport()
    );

    var exception = AssertThrows<AmvisionTriggerException>(() => client.InvokeImage(new ImageTriggerRequest
    {
        ImageBytes = new byte[] { 1 }
    }));
    AssertEqual("invalid_reply", exception.ErrorCode);
}

// 验证 transport timeout 会按 SDK timeout 异常透出。
static void TimeoutExceptionIsPropagated()
{
    using var client = new AmvisionTriggerClient(
        new AmvisionTriggerClientOptions { TriggerSourceId = "trigger-source-04" },
        new TimeoutTransport()
    );

    var exception = AssertThrows<AmvisionTriggerTimeoutException>(() => client.InvokeImage(new ImageTriggerRequest
    {
        ImageBytes = new byte[] { 1 }
    }));
    AssertEqual("timeout", exception.ErrorCode);
}

// 验证 WorkflowAppRuntime image-base64 invoke 会构造正确的 HTTP 请求。
static void WorkflowRuntimeImageInvokeBuildsExpectedHttpRequest()
{
    var handler = new FakeHttpMessageHandler(
        HttpStatusCode.OK,
        "{\"workflow_run_id\":\"workflow-run-http\",\"state\":\"failed\"}"
    );
    using var httpClient = new HttpClient(handler)
    {
        BaseAddress = new Uri("http://127.0.0.1:8000/")
    };
    using var client = new AmvisionWorkflowClient(
        new AmvisionWorkflowClientOptions
        {
            BaseApiUrl = "http://127.0.0.1:8000",
            AccessToken = "amvision-default-user-token"
        },
        httpClient
    );

    var response = client.InvokeWorkflowAppRuntimeWithImageBase64Async(
        "runtime-07",
        new WorkflowRuntimeImageInvokeRequest
        {
            ImageBytes = new byte[] { 1, 2, 3 },
            MediaType = "image/png",
            TimeoutSeconds = 5,
            ExecutionMetadata = { ["scenario"] = "opencv-process-save-image-zeromq" }
        }).GetAwaiter().GetResult();

    AssertEqual(HttpMethod.Post, handler.LastMethod);
    AssertEqual("http://127.0.0.1:8000/api/v1/workflows/app-runtimes/runtime-07/invoke?response_mode=run", handler.LastRequestUri?.ToString());
    AssertEqual("Bearer amvision-default-user-token", handler.LastHeaders["Authorization"].Single());
    AssertEqual(HttpStatusCode.OK, response.StatusCode);
    AssertEqual(true, response.IsSuccessStatusCode);

    using var document = JsonDocument.Parse(handler.LastBody);
    var root = document.RootElement;
    AssertEqual("AQID", root.GetProperty("input_bindings").GetProperty("request_image_base64").GetProperty("image_base64").GetString());
    AssertEqual("image/png", root.GetProperty("input_bindings").GetProperty("request_image_base64").GetProperty("media_type").GetString());
    AssertEqual("opencv-process-save-image-zeromq", root.GetProperty("execution_metadata").GetProperty("scenario").GetString());
    AssertEqual(5, root.GetProperty("timeout_seconds").GetInt32());
}

// 验证 runtime invoke JSON 支持当前后端的顶层公开 input 字段形态。
static void WorkflowRuntimeInvokeSupportsDirectInputJson()
{
    var request = new WorkflowRuntimeInvokeRequest
    {
        UseDirectInputBindings = true,
        TimeoutSeconds = 9
    };
    request.InputBindings["request_image_base64"] = new Dictionary<string, object?>
    {
        ["image_base64"] = "AQID",
        ["media_type"] = "image/png"
    };
    request.ExecutionMetadata["source"] = "dotnet-test";

    using var document = JsonDocument.Parse(request.ToJson());
    var root = document.RootElement;
    AssertEqual(false, root.TryGetProperty("input_bindings", out _));
    AssertEqual("AQID", root.GetProperty("request_image_base64").GetProperty("image_base64").GetString());
    AssertEqual("dotnet-test", root.GetProperty("execution_metadata").GetProperty("source").GetString());
    AssertEqual(9, root.GetProperty("timeout_seconds").GetInt32());

    var parsed = WorkflowRuntimeInvokeRequest.Parse(request.ToJson());
    AssertEqual(true, parsed.UseDirectInputBindings);
    AssertEqual(1, parsed.InputBindings.Count);
}

// 验证 Workflow runtime/run 当前正式接口路径和 query。
static void WorkflowRuntimeRunAndLifecycleEndpointsUseExpectedHttpRequests()
{
    var handler = new FakeHttpMessageHandler(HttpStatusCode.OK, "{\"format_id\":\"amvision.workflow-app-runtime.v1\",\"workflow_runtime_id\":\"runtime-1\",\"project_id\":\"project-1\",\"application_id\":\"app-1\",\"desired_state\":\"running\",\"observed_state\":\"running\",\"created_at\":\"2026-07-02T00:00:00Z\",\"updated_at\":\"2026-07-02T00:00:00Z\"}");
    using var httpClient = new HttpClient(handler) { BaseAddress = new Uri("http://127.0.0.1:8000/") };
    using var client = CreateWorkflowClient(httpClient);

    _ = client.RestartWorkflowAppRuntimeAsync("runtime-1").GetAwaiter().GetResult();
    AssertEqual(HttpMethod.Post, handler.LastMethod);
    AssertEqual("http://127.0.0.1:8000/api/v1/workflows/app-runtimes/runtime-1/restart", handler.LastRequestUri?.ToString());

    _ = client.ListWorkflowAppRuntimesAsync("project-1", offset: 2, limit: 3).GetAwaiter().GetResult();
    AssertEqual(HttpMethod.Get, handler.LastMethod);
    AssertEqual("http://127.0.0.1:8000/api/v1/workflows/app-runtimes?project_id=project-1&offset=2&limit=3", handler.LastRequestUri?.ToString());

    _ = client.ListWorkflowAppRuntimeInstancesAsync("runtime-1").GetAwaiter().GetResult();
    AssertEqual(HttpMethod.Get, handler.LastMethod);
    AssertEqual("http://127.0.0.1:8000/api/v1/workflows/app-runtimes/runtime-1/instances", handler.LastRequestUri?.ToString());

    _ = client.GetWorkflowRunAsync("workflow-run-1").GetAwaiter().GetResult();
    AssertEqual(HttpMethod.Get, handler.LastMethod);
    AssertEqual("http://127.0.0.1:8000/api/v1/workflows/runs/workflow-run-1?response_mode=run", handler.LastRequestUri?.ToString());

    _ = client.GetWorkflowRunEventsAsync("workflow-run-1", afterSequence: 5, limit: 10).GetAwaiter().GetResult();
    AssertEqual(HttpMethod.Get, handler.LastMethod);
    AssertEqual("http://127.0.0.1:8000/api/v1/workflows/runs/workflow-run-1/events?after_sequence=5&limit=10", handler.LastRequestUri?.ToString());

    _ = client.CancelWorkflowRunAsync("workflow-run-1").GetAwaiter().GetResult();
    AssertEqual(HttpMethod.Post, handler.LastMethod);
    AssertEqual("http://127.0.0.1:8000/api/v1/workflows/runs/workflow-run-1/cancel", handler.LastRequestUri?.ToString());
}

// 验证 TriggerSource create/list/delete 当前正式接口路径和 body。
static void TriggerSourceCreateListDeleteUsesExpectedHttpRequests()
{
    var handler = new FakeHttpMessageHandler(HttpStatusCode.Created, "{\"format_id\":\"amvision.workflow-trigger-source.v1\",\"trigger_source_id\":\"trigger-source-1\",\"project_id\":\"project-1\",\"display_name\":\"line trigger\",\"trigger_kind\":\"zeromq-topic\",\"workflow_runtime_id\":\"runtime-1\",\"submit_mode\":\"sync\",\"enabled\":false,\"desired_state\":\"stopped\",\"observed_state\":\"stopped\",\"transport_config\":{\"bind_endpoint\":\"tcp://127.0.0.1:5555\"},\"input_binding_mapping\":{},\"health_summary\":{},\"created_at\":\"2026-07-02T00:00:00Z\",\"updated_at\":\"2026-07-02T00:00:00Z\"}");
    using var httpClient = new HttpClient(handler) { BaseAddress = new Uri("http://127.0.0.1:8000/") };
    using var client = CreateWorkflowClient(httpClient);

    var createRequest = new WorkflowTriggerSourceCreateRequest
    {
        TriggerSourceId = "trigger-source-1",
        ProjectId = "project-1",
        DisplayName = "line trigger",
        WorkflowRuntimeId = "runtime-1",
        Enabled = false,
        IdempotencyKeyPath = "payload.idempotency_key"
    };
    createRequest.TransportConfig["bind_endpoint"] = "tcp://127.0.0.1:5555";
    createRequest.InputBindingMapping["request_image_ref"] = new WorkflowTriggerInputBindingMappingItem
    {
        Source = "payload.request_image_ref",
        PayloadTypeId = "image-ref.v1"
    };

    _ = client.CreateTriggerSourceAsync(createRequest).GetAwaiter().GetResult();
    AssertEqual(HttpMethod.Post, handler.LastMethod);
    AssertEqual("http://127.0.0.1:8000/api/v1/workflows/trigger-sources", handler.LastRequestUri?.ToString());
    using (var document = JsonDocument.Parse(handler.LastBody))
    {
        var root = document.RootElement;
        AssertEqual("trigger-source-1", root.GetProperty("trigger_source_id").GetString());
        AssertEqual("sync", root.GetProperty("submit_mode").GetString());
        AssertEqual("ack-after-run-finished", root.GetProperty("ack_policy").GetString());
        AssertEqual("sync-reply", root.GetProperty("result_mode").GetString());
        AssertEqual("payload.idempotency_key", root.GetProperty("idempotency_key_path").GetString());
        AssertEqual("payload.request_image_ref", root.GetProperty("input_binding_mapping").GetProperty("request_image_ref").GetProperty("source").GetString());
    }

    _ = client.ListTriggerSourcesAsync("project-1", limit: 7).GetAwaiter().GetResult();
    AssertEqual(HttpMethod.Get, handler.LastMethod);
    AssertEqual("http://127.0.0.1:8000/api/v1/workflows/trigger-sources?project_id=project-1&offset=0&limit=7", handler.LastRequestUri?.ToString());

    _ = client.DeleteTriggerSourceAsync("trigger-source-1").GetAwaiter().GetResult();
    AssertEqual(HttpMethod.Delete, handler.LastMethod);
    AssertEqual("http://127.0.0.1:8000/api/v1/workflows/trigger-sources/trigger-source-1", handler.LastRequestUri?.ToString());
}

// 验证 typed response 方法能解析后端稳定字段。
static void TypedResponsesDeserializeWorkflowResponses()
{
    var handler = new FakeHttpMessageHandler(
        HttpStatusCode.OK,
        "{\"format_id\":\"amvision.workflow-app-runtime.v1\",\"workflow_runtime_id\":\"runtime-typed\",\"project_id\":\"project-1\",\"application_id\":\"app-1\",\"desired_state\":\"running\",\"observed_state\":\"running\",\"health_summary\":{\"worker_alive\":true},\"metadata\":{},\"created_at\":\"2026-07-02T00:00:00Z\",\"updated_at\":\"2026-07-02T00:00:00Z\"}"
    );
    using var httpClient = new HttpClient(handler) { BaseAddress = new Uri("http://127.0.0.1:8000/") };
    using var client = CreateWorkflowClient(httpClient);

    var runtime = client.GetWorkflowAppRuntimeHealthResponseAsync("runtime-typed").GetAwaiter().GetResult();
    AssertEqual("runtime-typed", runtime.WorkflowRuntimeId);
    AssertEqual("running", runtime.ObservedState);
    AssertEqual(true, runtime.HealthSummary["worker_alive"].GetBoolean());
}

// 验证 TriggerSource health 管理 API会命中预期路径。
static void TriggerSourceHealthUsesExpectedHttpEndpoint()
{
    var handler = new FakeHttpMessageHandler(
        HttpStatusCode.OK,
        "{\"trigger_source_id\":\"zeromq-trigger-source-06\",\"adapter_running\":true}"
    );
    using var httpClient = new HttpClient(handler)
    {
        BaseAddress = new Uri("http://127.0.0.1:8000/")
    };
    using var client = new AmvisionWorkflowClient(
        new AmvisionWorkflowClientOptions
        {
            BaseApiUrl = "http://127.0.0.1:8000",
            AccessToken = "amvision-default-user-token"
        },
        httpClient
    );

    var response = client.GetTriggerSourceHealthAsync("zeromq-trigger-source-06").GetAwaiter().GetResult();

    AssertEqual(HttpMethod.Get, handler.LastMethod);
    AssertEqual(
        "http://127.0.0.1:8000/api/v1/workflows/trigger-sources/zeromq-trigger-source-06/health",
        handler.LastRequestUri?.ToString());
    AssertEqual(HttpStatusCode.OK, response.StatusCode);
}

// 验证 backend-service 错误 envelope 会被解析到 SDK HTTP 响应对象中。
static void WorkflowApiResponseParsesBackendErrorEnvelope()
{
    var handler = new FakeHttpMessageHandler(
        HttpStatusCode.BadRequest,
        "{\"error\":{\"code\":\"invalid_request\",\"message\":\"bad request\",\"details\":{\"binding_id\":\"request_image_base64\"}}}"
    );
    using var httpClient = new HttpClient(handler)
    {
        BaseAddress = new Uri("http://127.0.0.1:8000/")
    };
    using var client = new AmvisionWorkflowClient(
        new AmvisionWorkflowClientOptions
        {
            BaseApiUrl = "http://127.0.0.1:8000",
            AccessToken = "amvision-default-user-token"
        },
        httpClient
    );

    var response = client.GetWorkflowAppRuntimeHealthAsync("runtime-07").GetAwaiter().GetResult();

    AssertEqual(HttpStatusCode.BadRequest, response.StatusCode);
    AssertEqual(false, response.IsSuccessStatusCode);
    AssertEqual("invalid_request", response.ErrorCode);
    AssertEqual("bad request", response.ErrorMessage);
    AssertEqual("request_image_base64", response.ErrorDetails["binding_id"].GetString());
}

// 验证 ZeroMQ helper 会生成常用 payload 和 idempotency_key。
static void ZeroMqEnvelopeAddsHelperPayload()
{
    var transport = new FakeTransport(
        "{\"format_id\":\"amvision.workflow-trigger-result.v1\",\"trigger_source_id\":\"trigger-source-06\",\"event_id\":\"event-1\",\"state\":\"accepted\",\"workflow_run_id\":\"workflow-run-1\",\"response_payload\":{},\"metadata\":{}}"
    );
    using var client = new AmvisionTriggerClient(
        new AmvisionTriggerClientOptions
        {
            TriggerSourceId = "trigger-source-06"
        },
        transport
    );

    _ = client.InvokeImage(new ImageTriggerRequest
    {
        ImageBytes = new byte[] { 1 },
        EventId = "event-1",
        MediaType = "image/jpeg"
    }
    .WithDeploymentInstance("deployment-instance-1")
    .WithIdempotencyKey("idem-1"));

    using var document = JsonDocument.Parse(Encoding.UTF8.GetString(transport.LastFrames[0]));
    var payload = document.RootElement.GetProperty("payload");
    AssertEqual("idem-1", payload.GetProperty("idempotency_key").GetString());
    AssertEqual(
        "deployment-instance-1",
        payload.GetProperty("deployment_request").GetProperty("value").GetProperty("deployment_instance_id").GetString());
}

// 验证生成的 ZeroMQ envelope 字段仍与 schema fixture 保持一致。
static void SchemaFixtureMatchesGeneratedEnvelope()
{
    var schemaPath = FindWorkspaceFile(Path.Combine("sdks", "schemas", "zeromq-trigger-envelope.v1.schema.json"));
    using var schemaDocument = JsonDocument.Parse(File.ReadAllText(schemaPath));
    var allowedProperties = new HashSet<string>(
        schemaDocument.RootElement.GetProperty("properties").EnumerateObject().Select(item => item.Name),
        StringComparer.Ordinal);

    var transport = new FakeTransport(
        "{\"format_id\":\"amvision.workflow-trigger-result.v1\",\"trigger_source_id\":\"trigger-source-schema\",\"event_id\":\"event-schema\",\"state\":\"accepted\",\"workflow_run_id\":\"workflow-run-schema\",\"response_payload\":{},\"metadata\":{}}"
    );
    using var client = new AmvisionTriggerClient(
        new AmvisionTriggerClientOptions
        {
            TriggerSourceId = "trigger-source-schema"
        },
        transport
    );

    _ = client.InvokeImage(new ImageTriggerRequest
    {
        ImageBytes = new byte[] { 1, 2 },
        EventId = "event-schema",
        MediaType = "image/png",
        Shape = new[] { 1, 2, 1 }
    }.WithIdempotencyKey("idem-schema"));

    using var envelopeDocument = JsonDocument.Parse(Encoding.UTF8.GetString(transport.LastFrames[0]));
    foreach (var property in envelopeDocument.RootElement.EnumerateObject())
    {
        if (!allowedProperties.Contains(property.Name))
        {
            throw new InvalidOperationException($"Envelope property {property.Name} is not declared by schema fixture.");
        }
    }

    AssertEqual(false, envelopeDocument.RootElement.TryGetProperty("format_id", out _));
    AssertEqual("idem-schema", envelopeDocument.RootElement.GetProperty("payload").GetProperty("idempotency_key").GetString());
}

// 可选真实 backend-service smoke；未设置环境变量时跳过。
static void BackendLocalSmokeTest()
{
    var baseUrl = Environment.GetEnvironmentVariable("AMVISION_DOTNET_SDK_SMOKE_BASE_URL");
    if (string.IsNullOrWhiteSpace(baseUrl))
    {
        Console.WriteLine("skipped: BackendLocalSmokeTest requires AMVISION_DOTNET_SDK_SMOKE_BASE_URL");
        return;
    }

    var token = Environment.GetEnvironmentVariable("AMVISION_DOTNET_SDK_SMOKE_TOKEN");
    var projectId = Environment.GetEnvironmentVariable("AMVISION_DOTNET_SDK_SMOKE_PROJECT_ID");
    using var client = new AmvisionWorkflowClient(new AmvisionWorkflowClientOptions
    {
        BaseApiUrl = baseUrl,
        AccessToken = string.IsNullOrWhiteSpace(token) ? "amvision-default-user-token" : token,
        Timeout = TimeSpan.FromSeconds(5)
    });

    var response = client.ListTriggerSourcesAsync(
        string.IsNullOrWhiteSpace(projectId) ? "project-1" : projectId,
        limit: 1).GetAwaiter().GetResult();
    response.EnsureSuccessStatusCode();
}

// 创建带默认 SDK 参数的 Workflow HTTP client。
static AmvisionWorkflowClient CreateWorkflowClient(HttpClient httpClient)
{
    return new AmvisionWorkflowClient(
        new AmvisionWorkflowClientOptions
        {
            BaseApiUrl = "http://127.0.0.1:8000",
            AccessToken = "amvision-default-user-token"
        },
        httpClient
    );
}

// 从当前目录向上查找仓库内文件。
static string FindWorkspaceFile(string relativePath)
{
    var directory = new DirectoryInfo(Environment.CurrentDirectory);
    while (directory is not null)
    {
        var candidate = Path.Combine(directory.FullName, relativePath);
        if (File.Exists(candidate))
        {
            return candidate;
        }

        directory = directory.Parent;
    }

    throw new FileNotFoundException($"Cannot find workspace file: {relativePath}");
}

// 断言两个值相等。
static void AssertEqual<T>(T expected, T actual)
{
    if (!EqualityComparer<T>.Default.Equals(expected, actual))
    {
        throw new InvalidOperationException($"Expected {expected}, got {actual}.");
    }
}

// 断言两个 byte 序列相等。
static void AssertSequence(byte[] expected, byte[] actual)
{
    if (!expected.SequenceEqual(actual))
    {
        throw new InvalidOperationException("Byte sequence mismatch.");
    }
}

// 断言指定调用会抛出目标异常类型。
static TException AssertThrows<TException>(Action action)
    where TException : Exception
{
    try
    {
        action();
    }
    catch (TException exception)
    {
        return exception;
    }

    throw new InvalidOperationException($"Expected exception {typeof(TException).Name}.");
}

// 申请一个当前可用的本地 TCP 端口。
static int GetFreeTcpPort()
{
    using var listener = new TcpListener(IPAddress.Loopback, 0);
    listener.Start();
    return ((IPEndPoint)listener.LocalEndpoint).Port;
}

internal sealed class FakeTransport : IZeroMqRequestTransport
{
    private readonly string? reply;

    // 初始化 fake transport。
    public FakeTransport(string? reply = null)
    {
        this.reply = reply;
    }

    public IReadOnlyList<byte[]> LastFrames { get; private set; } = Array.Empty<byte[]>();

    // 记录请求 frames 并返回预设 reply。
    public IReadOnlyList<byte[]> Send(IReadOnlyList<byte[]> frames, TimeSpan timeout)
    {
        _ = timeout;
        LastFrames = frames.ToArray();
        return reply is null ? Array.Empty<byte[]>() : new[] { Encoding.UTF8.GetBytes(reply) };
    }

    // 释放 fake transport。
    public void Dispose()
    {
    }
}

internal sealed class TimeoutTransport : IZeroMqRequestTransport
{
    // 直接抛出 timeout 异常。
    public IReadOnlyList<byte[]> Send(IReadOnlyList<byte[]> frames, TimeSpan timeout)
    {
        _ = (frames, timeout);
        throw new AmvisionTriggerTimeoutException("timeout");
    }

    // 释放 timeout transport。
    public void Dispose()
    {
    }
}

internal sealed class FakeHttpMessageHandler : HttpMessageHandler
{
    private readonly HttpStatusCode statusCode;
    private readonly string responseContent;

    // 初始化 fake HTTP handler。
    public FakeHttpMessageHandler(HttpStatusCode statusCode, string responseContent)
    {
        this.statusCode = statusCode;
        this.responseContent = responseContent;
    }

    public HttpMethod? LastMethod { get; private set; }

    public Uri? LastRequestUri { get; private set; }

    public string LastBody { get; private set; } = string.Empty;

    public Dictionary<string, string[]> LastHeaders { get; } = new Dictionary<string, string[]>(StringComparer.OrdinalIgnoreCase);

    // 记录最近一次 HTTP 请求并返回预设 JSON 响应。
    protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
    {
        _ = cancellationToken;
        LastMethod = request.Method;
        LastRequestUri = request.RequestUri;
        LastHeaders.Clear();
        foreach (var header in request.Headers)
        {
            LastHeaders[header.Key] = header.Value.ToArray();
        }

        LastBody = request.Content is null
            ? string.Empty
            : await request.Content.ReadAsStringAsync().ConfigureAwait(false);
        return new HttpResponseMessage(statusCode)
        {
            Content = new StringContent(responseContent, Encoding.UTF8, "application/json")
        };
    }
}
