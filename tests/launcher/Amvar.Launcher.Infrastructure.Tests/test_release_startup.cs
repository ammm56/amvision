using Amvar.Launcher.Core.Application;
using Amvar.Launcher.Core.Configuration;
using Amvar.Launcher.Core.Lifecycle;
using Amvar.Launcher.Core.Runtime;
using Amvar.Launcher.Infrastructure.Diagnostics;
using Amvar.Launcher.Infrastructure.Http;
using Amvar.Launcher.Infrastructure.Runtime;

namespace Amvar.Launcher.Infrastructure.Tests;

/// <summary>显式指定真实发行目录后，验证与桌面相同的连接、启动及退出用例。</summary>
public sealed class ReleaseStartupTests
{
    [ReleaseStartupFact]
    public async Task Release_cold_start_uses_bundled_full_stack_and_exit_reclaims_it()
    {
        var root = Path.GetFullPath(Environment.GetEnvironmentVariable("AMVAR_LAUNCHER_RELEASE_TEST_ROOT")!);
        using var probe = new HttpServiceProbe();
        Assert.Equal(ProbeKind.NotListening, (await probe.ProbeAsync(default)).Kind);
        var log = new FileLauncherLog(Path.Combine(root, "launcher", "logs", "release-acceptance"));
        using var stack = new FullStackController(Path.Combine(root, "launcher", "data", "release-acceptance"), log);
        var coordinator = new LauncherCoordinator(new BackendSessionController(probe, stack, TimeProvider.System), log);
        try
        {
            await coordinator.InitializeAsync(new LauncherSettings(), new ProjectInstallation(root))
                .WaitAsync(TimeSpan.FromMinutes(6));
            Assert.True(coordinator.Snapshot.NavigationId == 1, coordinator.Snapshot.Problem);
            Assert.Equal(SessionManagementMode.ManagedFullStack, coordinator.Snapshot.Mode);
            Assert.Equal(ProbeKind.Available, (await probe.ProbeAsync(default)).Kind);
            Assert.True(File.Exists(Path.Combine(root, "logs", "full-stack", "runtime-state.json")));
        }
        finally
        {
            Assert.True(await coordinator.RequestExitAsync().WaitAsync(TimeSpan.FromMinutes(2)), coordinator.Snapshot.Problem);
        }
        Assert.Equal(ApplicationPhase.ReadyToExit, coordinator.Snapshot.Application);
        Assert.Equal(ProbeKind.NotListening, (await probe.ProbeAsync(default)).Kind);
        Assert.False(File.Exists(Path.Combine(root, "logs", "full-stack", "runtime-state.json")));
    }

    private sealed class ReleaseStartupFactAttribute : FactAttribute
    {
        public ReleaseStartupFactAttribute()
        {
            if (!OperatingSystem.IsWindows() || string.IsNullOrWhiteSpace(Environment.GetEnvironmentVariable("AMVAR_LAUNCHER_RELEASE_TEST_ROOT")))
                Skip = "显式设置 AMVAR_LAUNCHER_RELEASE_TEST_ROOT，并先停止开发服务。";
        }
    }
}
