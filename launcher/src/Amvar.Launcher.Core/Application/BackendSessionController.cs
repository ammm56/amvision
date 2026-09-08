using Amvar.Launcher.Core.Abstractions;
using Amvar.Launcher.Core.Configuration;
using Amvar.Launcher.Core.Lifecycle;
using Amvar.Launcher.Core.Runtime;

namespace Amvar.Launcher.Core.Application;

/// <summary>串行连接流程；外部服务只观察，本次创建任务才具备停止权限。</summary>
public sealed class BackendSessionController(IServiceProbe probe, IStackController stack, TimeProvider clock)
{
    public bool OwnsService => stack.HasOwnedSession;

    public async Task ConnectAsync(LauncherSettings settings, ProjectInstallation installation,
        Action<BackendPhase, string?, TimeSpan, bool> report, CancellationToken token)
    {
        var started = clock.GetTimestamp();
        if (!settings.ManageService) return;
        while (true)
        {
            token.ThrowIfCancellationRequested();
            var result = await probe.ProbeAsync(token);
            if (result.Kind == ProbeKind.Available && !OwnsService) return;
            var observation = await stack.ObserveAsync(installation, token);
            if (observation.Phase == StackPhase.Failed)
                throw new InvalidOperationException(observation.Error ?? "视觉服务启动失败。");
            var inProgress = observation.Phase is StackPhase.Starting or StackPhase.Stopping;
            if (result.Kind == ProbeKind.Available && !inProgress &&
                (!OwnsService || observation.Phase == StackPhase.Running))
                return;

            if (observation.Phase == StackPhase.Absent && result.Kind == ProbeKind.NotListening)
            {
                if (OwnsService) throw new InvalidOperationException("本次启动的服务已结束，请检查日志。");
                await stack.StartAsync(installation, token);
            }
            else if (!inProgress && !OwnsService)
                throw new InvalidOperationException(result.Error ?? "服务正在运行但页面不可访问。");

            var elapsed = clock.GetElapsedTime(started);
            var expired = elapsed >= settings.StartupTimeout;
            report(BackendPhase.Starting, expired ? "启动等待时间较长，可继续等待或查看日志。" : null, elapsed, expired);
            if (expired) return;
            await Task.Delay(TimeSpan.FromSeconds(1), clock, token);
        }
    }

    public Task<StackStopResult> StopAsync(CancellationToken token) =>
        OwnsService ? stack.StopAsync(token) : Task.FromResult(new StackStopResult(true));
}
