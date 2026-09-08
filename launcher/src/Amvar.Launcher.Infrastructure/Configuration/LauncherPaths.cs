using Amvar.Launcher.Core.Runtime;

namespace Amvar.Launcher.Infrastructure.Configuration;

public sealed class LauncherPaths(string programRoot)
{
    public string ProgramRoot { get; } = Path.GetFullPath(programRoot);
    public string InstallationRoot => Path.GetFileName(Path.TrimEndingDirectorySeparator(ProgramRoot)).Equals("launcher", StringComparison.OrdinalIgnoreCase)
        ? Directory.GetParent(Path.TrimEndingDirectorySeparator(ProgramRoot))!.FullName : ProgramRoot;
    public string SettingsFile => Path.Combine(ProgramRoot, "config", "launcher.json");
    public string DataDirectory => Path.Combine(ProgramRoot, "data", "launcher");
    public string WebViewDirectory => Path.Combine(DataDirectory, "webview");
    public string LogDirectory => Path.Combine(ProgramRoot, "logs", "launcher");
    public string FixedWebViewDirectory => Path.Combine(ProgramRoot, "tools", "webview2", "win-x64");
    public ProjectInstallation ResolveInstallation(string root) => new(Path.GetFullPath(root, InstallationRoot));
}
