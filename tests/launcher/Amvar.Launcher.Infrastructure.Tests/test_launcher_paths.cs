using Amvar.Launcher.Infrastructure.Configuration;

namespace Amvar.Launcher.Infrastructure.Tests;

public sealed class LauncherPathTests
{
    [Fact]
    public void Packaged_dependencies_and_service_root_are_separate()
    {
        var root = Path.GetFullPath("release/full-windows-x64-cpu");
        var paths = new LauncherPaths(Path.Combine(root, "launcher"));
        Assert.Equal(root, paths.ResolveInstallation(".").RootDirectory);
        Assert.Equal(Path.Combine(root, "launcher", "config", "launcher.json"), paths.SettingsFile);
        Assert.StartsWith(Path.Combine(root, "launcher"), paths.FixedWebViewDirectory);
    }
}
