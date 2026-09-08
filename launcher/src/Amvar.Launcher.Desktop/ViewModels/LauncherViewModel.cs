using System.ComponentModel;
using System.Runtime.CompilerServices;
using Amvar.Launcher.Core.Lifecycle;
using Amvar.Launcher.Core.Runtime;

namespace Amvar.Launcher.Desktop.ViewModels;

/// <summary>将用例快照投影成显示内容，不管理进程或持久化。</summary>
public sealed class LauncherViewModel : INotifyPropertyChanged
{
    public event PropertyChangedEventHandler? PropertyChanged;
    public string Heading { get; private set; } = "正在准备工作台";
    public string Detail { get; private set; } = "正在读取启动配置";
    public string Elapsed { get; private set; } = "";
    public bool Busy { get; private set; } = true;
    public bool CanRetry { get; private set; }
    public bool HasProblem { get; private set; }
    public bool ShowBrowser { get; private set; }
    public string Mode { get; private set; } = "本地工作台";
    public void Apply(LauncherSnapshot snapshot)
    {
        HasProblem = snapshot.Problem != null || snapshot.WaitExpired;
        CanRetry = snapshot.Application is ApplicationPhase.Active or ApplicationPhase.ExitBlocked && HasProblem;
        Busy = !HasProblem && snapshot.Backend != BackendPhase.Connected;
        ShowBrowser = snapshot.Application == ApplicationPhase.Active && snapshot.Backend == BackendPhase.Connected;
        Heading = snapshot.Application switch
        {
            ApplicationPhase.ExitRequested => "正在退出",
            ApplicationPhase.ExitBlocked => "服务尚未停止",
            ApplicationPhase.InitializationFailed => "请检查启动配置",
            _ => snapshot.Backend switch
            {
                BackendPhase.Connected => "工作台已就绪",
                BackendPhase.Starting => snapshot.WaitExpired ? "服务仍在启动" : "正在启动视觉服务",
                BackendPhase.Faulted or BackendPhase.Unavailable => "暂时无法打开工作台",
                _ => "正在准备工作台"
            }
        };
        Detail = snapshot.Problem ?? (snapshot.Application == ApplicationPhase.ExitRequested
            ? "正在等待本次启动的服务结束" : snapshot.Backend == BackendPhase.Starting
                ? "首次启动需要一些时间，可关闭窗口到托盘继续等待" : "正在连接 127.0.0.1:5600");
        Elapsed = snapshot.Elapsed.TotalSeconds >= 1 ? $"已等待 {(int)snapshot.Elapsed.TotalSeconds} 秒" : "";
        Mode = snapshot.Mode == SessionManagementMode.ManagedFullStack ? "由启动器管理服务" : "仅连接现有服务";
        Notify("");
    }
    private void Notify([CallerMemberName] string? name = null) => PropertyChanged?.Invoke(this, new(name));
}
