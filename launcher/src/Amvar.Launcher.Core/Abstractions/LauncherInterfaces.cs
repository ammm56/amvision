using Amvar.Launcher.Core.Configuration;
using Amvar.Launcher.Core.Runtime;

namespace Amvar.Launcher.Core.Abstractions;

public interface ISettingsStore
{
    Task<SettingsLoadResult> LoadAsync(CancellationToken cancellationToken);
    Task SaveAsync(LauncherSettings settings, CancellationToken cancellationToken);
}
public interface IServiceProbe { Task<ServiceProbeResult> ProbeAsync(CancellationToken cancellationToken); }
public interface IStackController
{
    bool HasOwnedSession { get; }
    Task<StackObservation> ObserveAsync(ProjectInstallation installation, CancellationToken cancellationToken);
    Task StartAsync(ProjectInstallation installation, CancellationToken cancellationToken);
    Task<StackStopResult> StopAsync(CancellationToken cancellationToken);
}
public interface ILauncherLog { void Write(string message, Exception? exception = null); }
