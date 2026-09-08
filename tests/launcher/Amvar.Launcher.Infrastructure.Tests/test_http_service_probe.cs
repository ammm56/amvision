using System.Diagnostics;
using System.Net;
using System.Net.Sockets;
using System.Text;
using Amvar.Launcher.Core.Runtime;
using Amvar.Launcher.Infrastructure.Http;

namespace Amvar.Launcher.Infrastructure.Tests;

public sealed class HttpServiceProbeTests
{
    [Fact]
    public async Task Unused_loopback_port_is_absent_without_waiting_for_tcp_timeout()
    {
        var listener = new TcpListener(IPAddress.Loopback, 0);
        listener.Start();
        var port = ((IPEndPoint)listener.LocalEndpoint).Port;
        listener.Stop();
        using var probe = new HttpServiceProbe(new Uri($"http://127.0.0.1:{port}"));
        var elapsed = Stopwatch.StartNew();
        Assert.Equal(ProbeKind.NotListening, (await probe.ProbeAsync(default)).Kind);
        Assert.True(elapsed.Elapsed < TimeSpan.FromSeconds(2));
    }

    [Fact]
    public async Task Occupied_but_unresponsive_port_is_not_treated_as_absent()
    {
        using var listener = new TcpListener(IPAddress.Any, 0);
        listener.Start();
        var port = ((IPEndPoint)listener.LocalEndpoint).Port;
        using var probe = new HttpServiceProbe(new Uri($"http://127.0.0.1:{port}"));
        Assert.Equal(ProbeKind.Unavailable, (await probe.ProbeAsync(default)).Kind);
    }

    [Fact]
    public async Task Healthy_service_with_html_is_available_then_absent_after_stop()
    {
        using var listener = new TcpListener(IPAddress.Loopback, 0);
        listener.Start();
        var port = ((IPEndPoint)listener.LocalEndpoint).Port;
        using var probe = new HttpServiceProbe(new Uri($"http://127.0.0.1:{port}"));
        var serving = Task.Run(async () =>
        {
            // TCP 探测连接不会发送 HTTP；随后分别处理 health 与主页请求。
            using var tcpProbe = await listener.AcceptTcpClientAsync();
            foreach (var (type, body) in new[] { ("application/json", "{\"status\":\"ok\",\"request_id\":\"probe-test\"}"), ("text/html", "<html></html>") })
            {
                using var connection = await listener.AcceptTcpClientAsync();
                var stream = connection.GetStream();
                using var reader = new StreamReader(stream, Encoding.ASCII, leaveOpen: true);
                while (await reader.ReadLineAsync() is { Length: > 0 }) { }
                await stream.WriteAsync(Encoding.ASCII.GetBytes($"HTTP/1.1 200 OK\r\nContent-Type: {type}\r\nContent-Length: {body.Length}\r\nConnection: close\r\n\r\n{body}"));
            }
        });
        var result = await probe.ProbeAsync(default);
        Assert.True(result.Kind == ProbeKind.Available, result.Error);
        await serving.WaitAsync(TimeSpan.FromSeconds(5));
        listener.Stop();
        Assert.Equal(ProbeKind.NotListening, (await probe.ProbeAsync(default)).Kind);
    }

    [Fact]
    public async Task Cancelled_probe_cannot_authorize_startup()
    {
        using var probe = new HttpServiceProbe();
        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => probe.ProbeAsync(new CancellationToken(true)));
    }
}
