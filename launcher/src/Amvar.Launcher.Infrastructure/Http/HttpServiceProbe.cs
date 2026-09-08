using System.Net.Sockets;
using Amvar.Launcher.Core.Abstractions;
using Amvar.Launcher.Core.Runtime;
using Amvar.Launcher.Infrastructure.Contracts;
using Amvar.Launcher.Infrastructure.Serialization;

namespace Amvar.Launcher.Infrastructure.Http;

public sealed class HttpServiceProbe : IServiceProbe, IDisposable
{
    private readonly HttpClient client = new(new HttpClientHandler { AllowAutoRedirect = false, UseProxy = false })
    { BaseAddress = ProjectInstallation.HomeUri, Timeout = TimeSpan.FromSeconds(2), MaxResponseContentBufferSize = 1024 * 1024 };
    public async Task<ServiceProbeResult> ProbeAsync(CancellationToken token)
    {
        using var timeout = CancellationTokenSource.CreateLinkedTokenSource(token);
        timeout.CancelAfter(TimeSpan.FromSeconds(2));
        try
        {
            using var socket = new TcpClient();
            await socket.ConnectAsync("127.0.0.1", 5600, timeout.Token);
        }
        catch (SocketException ex) when (ex.SocketErrorCode == SocketError.ConnectionRefused)
        { return new(ProbeKind.NotListening); }
        catch (Exception ex) when (ex is SocketException or OperationCanceledException)
        {
            token.ThrowIfCancellationRequested();
            return new(ProbeKind.Unavailable, "连接视觉服务超时或失败。");
        }
        try
        {
            var json = await client.GetStringAsync("api/v1/system/health", token);
            var health = LauncherJson.Read<ServiceHealthResponse>(json, false);
            if (health.Status != "ok") return new(ProbeKind.Unavailable, "视觉服务健康检查未通过。");
            using var home = await client.GetAsync("/", token);
            return home.IsSuccessStatusCode && home.Content.Headers.ContentType?.MediaType == "text/html"
                ? new(ProbeKind.Available) : new(ProbeKind.Unavailable, "视觉服务未提供前端页面，请检查发行资源。");
        }
        catch (Exception ex) when (ex is not OperationCanceledException || !token.IsCancellationRequested)
        { return new(ProbeKind.Unavailable, "端口已被占用，页面不可用：" + ex.Message); }
    }
    public void Dispose() => client.Dispose();
}
