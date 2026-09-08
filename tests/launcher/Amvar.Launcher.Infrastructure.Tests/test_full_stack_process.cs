using Amvar.Launcher.Core.Abstractions;
using Amvar.Launcher.Core.Runtime;
using Amvar.Launcher.Infrastructure.Runtime;

namespace Amvar.Launcher.Infrastructure.Tests;

public sealed class FullStackProcessTests
{
    // 普通 dotnet test 只执行不依赖 Python 的测试；现场脚本显式启用真实进程测试。
    [ControlledProcessFact]
    public async Task Managed_batch_registers_own_root_and_stops_its_worker()
    {
        var root = Environment.GetEnvironmentVariable("AMVAR_LAUNCHER_TEST_ROOT");
        Assert.NotNull(root);
        var listener = new System.Net.Sockets.TcpListener(System.Net.IPAddress.Loopback, 0);
        listener.Start();
        var port = ((System.Net.IPEndPoint)listener.LocalEndpoint).Port;
        listener.Stop();
        await File.WriteAllTextAsync(Path.Combine(root, "listener-port.txt"), port.ToString());
        using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(45));
        using var controller = new FullStackController(Path.Combine(root, "requests"), new Amvar.Launcher.Infrastructure.Diagnostics.FileLauncherLog(Path.Combine(root, "logs", "launcher")), port);
        var installation = new ProjectInstallation(root);
        Assert.Equal(StackPhase.Absent, (await controller.ObserveAsync(installation, timeout.Token)).Phase);
        await controller.StartAsync(installation, timeout.Token);
        try
        {
            Assert.True(controller.HasOwnedSession);
            StackObservation observation;
            do
            {
                await Task.Delay(150, timeout.Token);
                observation = await controller.ObserveAsync(installation, timeout.Token);
                Assert.NotEqual(StackPhase.Failed, observation.Phase);
            } while (observation.Phase != StackPhase.Running);
        }
        finally
        {
            using var cleanup = new CancellationTokenSource(TimeSpan.FromSeconds(90));
            var stopped = await controller.StopAsync(cleanup.Token);
            Assert.True(stopped.Succeeded, stopped.Error);
        }
        Assert.False(File.Exists(Path.Combine(root, "logs", "full-stack", "runtime-state.json")));
    }
    private sealed class TestLog : ILauncherLog
    { public void Write(string message, Exception? exception = null) { } }

    [ControlledProcessFact]
    public async Task Exit_immediately_after_creation_waits_for_early_state_and_reaps_children()
    {
        var root = Environment.GetEnvironmentVariable("AMVAR_LAUNCHER_TEST_ROOT")!;
        await File.WriteAllTextAsync(Path.Combine(root, "listener-port.txt"), "0");
        using var controller = new FullStackController(Path.Combine(root, "requests"), new TestLog());
        using var cleanup = new CancellationTokenSource(TimeSpan.FromSeconds(30));
        await controller.StartAsync(new(root), cleanup.Token);
        var stopped = await controller.StopAsync(cleanup.Token);
        Assert.True(stopped.Succeeded, stopped.Error);
        Assert.False(File.Exists(Path.Combine(root, "logs", "full-stack", "runtime-state.json")));
    }

    [ControlledProcessFact]
    public async Task Unrelated_listener_is_rejected_and_survives_owned_stack_stop()
    {
        var root = Environment.GetEnvironmentVariable("AMVAR_LAUNCHER_TEST_ROOT")!;
        using var external = new System.Net.Sockets.TcpListener(System.Net.IPAddress.Loopback, 0);
        external.Start();
        var port = ((System.Net.IPEndPoint)external.LocalEndpoint).Port;
        await File.WriteAllTextAsync(Path.Combine(root, "listener-port.txt"), "0");
        using var controller = new FullStackController(Path.Combine(root, "requests"), new TestLog(), port);
        using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(30));
        await controller.StartAsync(new(root), timeout.Token);
        try
        {
            StackObservation observation;
            do { await Task.Delay(150, timeout.Token); observation = await controller.ObserveAsync(new(root), timeout.Token); }
            while (observation.Phase == StackPhase.Starting);
            Assert.Equal(StackPhase.Failed, observation.Phase);
            Assert.Contains("其他进程", observation.Error);
        }
        finally
        {
            using var cleanup = new CancellationTokenSource(TimeSpan.FromSeconds(30));
            var result = await controller.StopAsync(cleanup.Token);
            Assert.True(result.Succeeded, result.Error);
        }
        using var client = new System.Net.Sockets.TcpClient();
        await client.ConnectAsync(System.Net.IPAddress.Loopback, port);
        Assert.True(client.Connected);
    }
}

public sealed class ControlledProcessFactAttribute : FactAttribute
{
    public ControlledProcessFactAttribute()
    {
        if (Environment.GetEnvironmentVariable("AMVAR_LAUNCHER_TEST_ROOT") == null)
            Skip = "通过 tests/launcher/test_process_integration.ps1 启用真实短进程夹具";
    }
}
