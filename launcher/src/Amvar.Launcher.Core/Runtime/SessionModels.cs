namespace Amvar.Launcher.Core.Runtime;

/// <summary>不可变安装目标；磁盘定位由 Infrastructure 解析。</summary>
public sealed record class ProjectInstallation(string RootDirectory)
{
    public static Uri HomeUri { get; } = new("http://127.0.0.1:5600");
}
public enum SessionManagementMode { ObserveOnly, ManagedFullStack }
public enum ProbeKind { Available, NotListening, Unavailable }
public sealed record class ServiceProbeResult(ProbeKind Kind, string? Error = null);
public enum StackPhase { Absent, Starting, Running, Failed, Stopping }
public sealed record class StackObservation(StackPhase Phase, string? Error = null);
public sealed record class StackStopResult(bool Succeeded, string? Error = null);
/// <summary>进程身份保留 Python 协议的 Unix 数值秒与完整参数列表。</summary>
public sealed record class ProcessIdentity(int Pid, double CreateTime, string Executable,
    string WorkingDirectory, IReadOnlyList<string> CommandLine);
