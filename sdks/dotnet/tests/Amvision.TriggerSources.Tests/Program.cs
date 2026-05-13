using System.Net;
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
    TimeoutExceptionIsPropagated
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