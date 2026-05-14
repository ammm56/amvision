using System.Net;
using System.Net.Http;
using System.Net.Sockets;
using System.Text;
using System.Text.Json;
using NetMQ;
using NetMQ.Sockets;
using Amvision.TriggerSources;

var tests = new Action[]
{
    InvokeImageBuildsExpectedEnvelope,
    InvokeImageUsesNetMqReqRepTransport,
    ErrorReplyRaisesTypedException,
    InvalidImageRequestIsRejected,
    EmptyReplyIsRejected,
    TimeoutExceptionIsPropagated,
    WorkflowRuntimeImageInvokeBuildsExpectedHttpRequest,
    TriggerSourceHealthUsesExpectedHttpEndpoint,
    WorkflowApiResponseParsesBackendErrorEnvelope
};

foreach (var test in tests)
{
    test();
    Console.WriteLine($"passed: {test.Method.Name}");
}

NetMQConfig.Cleanup(block: false);

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
            DefaultInputBinding = "request_image",
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
    AssertEqual("request_image", root.GetProperty("input_binding").GetString());
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
            PrincipalId = "user-1",
            ProjectIds = "project-1",
            Scopes = "workflows:read,workflows:write"
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
    AssertEqual("http://127.0.0.1:8000/api/v1/workflows/app-runtimes/runtime-07/invoke", handler.LastRequestUri?.ToString());
    AssertEqual("user-1", handler.LastHeaders["x-amvision-principal-id"].Single());
    AssertEqual("project-1", handler.LastHeaders["x-amvision-project-ids"].Single());
    AssertEqual("workflows:read,workflows:write", handler.LastHeaders["x-amvision-scopes"].Single());
    AssertEqual(HttpStatusCode.OK, response.StatusCode);
    AssertEqual(true, response.IsSuccessStatusCode);

    using var document = JsonDocument.Parse(handler.LastBody);
    var root = document.RootElement;
    AssertEqual("AQID", root.GetProperty("input_bindings").GetProperty("request_image_base64").GetProperty("image_base64").GetString());
    AssertEqual("image/png", root.GetProperty("input_bindings").GetProperty("request_image_base64").GetProperty("media_type").GetString());
    AssertEqual("opencv-process-save-image-zeromq", root.GetProperty("execution_metadata").GetProperty("scenario").GetString());
    AssertEqual(5, root.GetProperty("timeout_seconds").GetInt32());
}

// 验证 TriggerSource health 控制面会命中预期路径。
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
            PrincipalId = "user-1",
            ProjectIds = "project-1",
            Scopes = "workflows:read,workflows:write"
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
            PrincipalId = "user-1",
            ProjectIds = "project-1",
            Scopes = "workflows:read,workflows:write"
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