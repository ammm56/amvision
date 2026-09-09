using Amvar.Launcher.Core.Runtime;

namespace Amvar.Launcher.Core.Lifecycle;

public enum ApplicationPhase { Initializing, InitializationFailed, Active, ExitRequested, ExitBlocked, ReadyToExit }
public enum BackendPhase { Unknown, Probing, Starting, Connected, Unavailable, Faulted, Stopping, StopFailed, Stopped, Checking }
/// <summary>界面只读快照；Revision 保证跨 UI 调度的顺序，NavigationId 表示一次显式导航请求。</summary>
public sealed record class LauncherSnapshot
{
    public long Revision { get; init; }
    public ApplicationPhase Application { get; init; } = ApplicationPhase.Initializing;
    public BackendPhase Backend { get; init; } = BackendPhase.Unknown;
    public SessionManagementMode Mode { get; init; }
    public long NavigationId { get; init; }
    public TimeSpan Elapsed { get; init; }
    public string? Problem { get; init; }
    public bool WaitExpired { get; init; }
}
