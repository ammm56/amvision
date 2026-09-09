using Amvar.Launcher.Core.Abstractions;
using Amvar.Launcher.Core.Configuration;
using Amvar.Launcher.Core.Lifecycle;
using Amvar.Launcher.Core.Runtime;

namespace Amvar.Launcher.Core.Application;

/// <summary>应用用例唯一入口；退出先取消连接，再等待创建登记完成，最后回收本次栈。</summary>
public sealed class LauncherCoordinator(BackendSessionController backend, ILauncherLog log)
{
    private readonly object gate = new();
    private CancellationTokenSource? connectionCancellation;
    private Task connection = Task.CompletedTask;
    private Task observation = Task.CompletedTask;
    private Task<bool>? exiting;
    private LauncherSettings? sessionSettings;
    private ProjectInstallation? installation;
    private long operation;
    public LauncherSnapshot Snapshot { get; private set; } = new();
    public event Action<LauncherSnapshot>? Changed;

    public void InitializationFailed(string message)
    {
        lock (gate)
            if (Snapshot.Application is ApplicationPhase.Initializing or ApplicationPhase.InitializationFailed)
                Publish(Snapshot with { Application = ApplicationPhase.InitializationFailed, Problem = message });
    }

    public Task InitializeAsync(LauncherSettings settings, ProjectInstallation target)
    {
        lock (gate)
        {
            if (Snapshot.Application is not (ApplicationPhase.Initializing or ApplicationPhase.InitializationFailed))
                return connection;
            settings.Validate();
            sessionSettings = settings;
            installation = target;
            log.Write($"启动配置：管理服务={settings.ManageService}，项目目录={target.RootDirectory}；只停止本次创建的服务。");
            Publish(Snapshot with { Application = ApplicationPhase.Active, Problem = null });
            return BeginConnect();
        }
    }

    public Task RetryAsync()
    {
        lock (gate)
        {
            if (Snapshot.Application != ApplicationPhase.Active || !connection.IsCompleted) return connection;
            return BeginConnect();
        }
    }

    private Task BeginConnect()
    {
        connectionCancellation?.Cancel();
        connectionCancellation?.Dispose();
        connectionCancellation = new();
        var id = ++operation;
        Publish(Snapshot with { Backend = BackendPhase.Probing, Problem = null, WaitExpired = false, Elapsed = TimeSpan.Zero });
        return connection = ConnectAsync(id, connectionCancellation.Token);
    }

    private async Task ConnectAsync(long id, CancellationToken token)
    {
        // 首次 yield 保证 Task 在任何回调或退出到来前已经登记。
        await Task.Yield();
        try
        {
            // 旧观察完成后才开始新连接，避免两代状态回调竞争。
            await observation;
            await backend.ConnectAsync(sessionSettings!, installation!, (phase, problem, elapsed, expired) =>
            {
                lock (gate)
                    if (id == operation && Snapshot.Application == ApplicationPhase.Active)
                        Publish(Snapshot with { Backend = phase, Problem = problem, Elapsed = elapsed,
                            WaitExpired = expired, Mode = Mode });
            }, token);
            lock (gate)
            {
                if (id != operation || Snapshot.Application != ApplicationPhase.Active || Snapshot.WaitExpired) return;
                Publish(Snapshot with { Mode = Mode, NavigationId = Snapshot.NavigationId + 1, Problem = null });
                observation = ObserveAsync(id, token);
            }
        }
        catch (OperationCanceledException) when (token.IsCancellationRequested) { }
        catch (Exception ex)
        {
            log.Write("连接服务失败", ex);
            lock (gate)
                if (id == operation && Snapshot.Application == ApplicationPhase.Active)
                    Publish(Snapshot with { Backend = BackendPhase.Faulted, Mode = Mode, Problem = ex.Message });
        }
    }

    private SessionManagementMode Mode => backend.OwnsService ? SessionManagementMode.ManagedFullStack : SessionManagementMode.ObserveOnly;

    private async Task ObserveAsync(long id, CancellationToken token)
    {
        try
        {
            await backend.ObserveAsync(installation!, (phase, problem) =>
            {
                lock (gate)
                    if (id == operation && Snapshot.Application == ApplicationPhase.Active &&
                        (Snapshot.Backend != phase || Snapshot.Problem != problem))
                        Publish(Snapshot with { Backend = phase, Problem = problem });
                // 不增加 NavigationId，不重载页面或丢弃未保存的 Workflow。
            }, token);
        }
        catch (OperationCanceledException) when (token.IsCancellationRequested) { }
    }

    public void ReportNavigation(long navigationId, bool succeeded, string? error = null)
    {
        lock (gate)
        {
            if (Snapshot.Application != ApplicationPhase.Active || navigationId != Snapshot.NavigationId) return;
            Publish(Snapshot with { Backend = succeeded ? BackendPhase.Connected : BackendPhase.Unavailable,
                Problem = succeeded ? null : error ?? "工作台载入失败。", WaitExpired = false });
        }
    }

    public Task<bool> RequestExitAsync()
    {
        lock (gate)
        {
            if (Snapshot.Application == ApplicationPhase.ReadyToExit) return Task.FromResult(true);
            if (exiting is { IsCompleted: false }) return exiting;
            ++operation;
            Publish(Snapshot with { Application = ApplicationPhase.ExitRequested, Problem = null, WaitExpired = false });
            connectionCancellation?.Cancel();
            return exiting = ExitAsync();
        }
    }

    private async Task<bool> ExitAsync()
    {
        await Task.Yield();
        try
        {
            await connection;
            await observation;
            if (backend.OwnsService)
            {
                lock (gate) Publish(Snapshot with { Backend = BackendPhase.Stopping, Mode = Mode });
                using var cleanup = new CancellationTokenSource(TimeSpan.FromSeconds(90));
                var result = await backend.StopAsync(cleanup.Token);
                if (!result.Succeeded) throw new InvalidOperationException(result.Error ?? "服务停止失败。");
            }
            lock (gate) Publish(Snapshot with { Application = ApplicationPhase.ReadyToExit,
                Backend = backend.OwnsService ? BackendPhase.Stopped : Snapshot.Backend, Problem = null });
            return true;
        }
        catch (Exception ex)
        {
            log.Write("退出失败", ex);
            lock (gate) Publish(Snapshot with { Application = ApplicationPhase.ExitBlocked,
                Backend = BackendPhase.StopFailed, Problem = ex.Message });
            return false;
        }
    }

    private void Publish(LauncherSnapshot next)
    {
        if (next.Application != Snapshot.Application || next.Backend != Snapshot.Backend || next.Mode != Snapshot.Mode)
            log.Write($"阶段 {next.Application}/{next.Backend}，服务归属={(next.Mode == SessionManagementMode.ManagedFullStack ? "本次启动器管理" : "尚未创建或外部服务")}");
        Snapshot = next with { Revision = Snapshot.Revision + 1 };
        // 订阅者仅投递 UI 消息，不在事件内等待 IO。
        Changed?.Invoke(Snapshot);
    }
}
