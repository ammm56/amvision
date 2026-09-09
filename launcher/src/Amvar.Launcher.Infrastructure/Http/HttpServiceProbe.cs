using System.Net.Sockets;
using System.Net;
using System.Net.NetworkInformation;
using System.Text.Json;
using Amvar.Launcher.Core.Abstractions;
using Amvar.Launcher.Core.Runtime;
using Amvar.Launcher.Infrastructure.Contracts;
using Amvar.Launcher.Infrastructure.Serialization;

namespace Amvar.Launcher.Infrastructure.Http;

public sealed class HttpServiceProbe : IServiceProbe, IDisposable
{
    private readonly HttpClient client;
    private readonly Uri address;

    public HttpServiceProbe() : this(ProjectInstallation.HomeUri) { }

    internal HttpServiceProbe(Uri address)
    {
        this.address = address;
        client = new(new HttpClientHandler { AllowAutoRedirect = false, UseProxy = false })
        { BaseAddress = address, Timeout = TimeSpan.FromSeconds(2), MaxResponseContentBufferSize = 1024 * 1024 };
    }

    // Windows 的未监听端口可能在 TCP 重试结束前触发连接超时。
    // 以本机监听表确认端口空闲，不把超时本身当成允许启动第二个服务的依据。
    private bool HasLocalListener() => IPGlobalProperties.GetIPGlobalProperties().GetActiveTcpListeners().Any(endpoint =>
        endpoint.Port == address.Port && (endpoint.Address.Equals(IPAddress.Loopback) ||
            endpoint.Address.Equals(IPAddress.Any) || endpoint.Address.Equals(IPAddress.IPv6Any) ||
            endpoint.Address.Equals(IPAddress.Loopback.MapToIPv6())));

    public async Task<ServiceProbeResult> ProbeAsync(CancellationToken token)
    {
        token.ThrowIfCancellationRequested();
        try
        {
            if (!HasLocalListener()) return new(ProbeKind.NotListening);
        }
        catch (NetworkInformationException ex)
        { return new(ProbeKind.Unavailable, "无法确认本机端口监听状态：" + ex.Message); }
        using var timeout = CancellationTokenSource.CreateLinkedTokenSource(token);
        timeout.CancelAfter(TimeSpan.FromSeconds(2));
        try
        {
            using var socket = new TcpClient();
            await socket.ConnectAsync(IPAddress.Loopback, address.Port, timeout.Token);
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

    public async Task<ServiceProbeResult> ProbeLivenessAsync(CancellationToken token)
    {
        // 新 HTTP 连接、短响应、总期限；运行期不反复读取 Broker 健康和首页。
        using var deadline = CancellationTokenSource.CreateLinkedTokenSource(token);
        deadline.CancelAfter(TimeSpan.FromSeconds(2));
        try
        {
            using var request = new HttpRequestMessage(HttpMethod.Get, "api/v1/system/liveness");
            request.Headers.ConnectionClose = true;
            using var response = await client.SendAsync(request, HttpCompletionOption.ResponseHeadersRead, deadline.Token);
            if (response.StatusCode != HttpStatusCode.OK || response.Content.Headers.ContentType?.MediaType != "application/json" ||
                response.Content.Headers.ContentLength is not (> 0 and <= 4096))
                return new(ProbeKind.Unavailable, "视觉服务接入检查响应无效。");
            await response.Content.LoadIntoBufferAsync(4096, deadline.Token);
            using var json = JsonDocument.Parse(await response.Content.ReadAsStringAsync(deadline.Token));
            var root = json.RootElement;
            return root.GetProperty("format_id").GetString() == "amvision.service-liveness.v1" &&
                root.GetProperty("phase").GetString() == "ready" &&
                root.GetProperty("pid").GetInt32() > 0 &&
                Guid.TryParseExact(root.GetProperty("instance_id").GetString(), "N", out _)
                ? new(ProbeKind.Available) : new(ProbeKind.Unavailable, "视觉服务尚未就绪。");
        }
        catch (Exception ex) when (ex is not OperationCanceledException || !token.IsCancellationRequested)
        { return new(ProbeKind.Unavailable, "视觉服务连接已中断：" + ex.Message); }
    }
}
