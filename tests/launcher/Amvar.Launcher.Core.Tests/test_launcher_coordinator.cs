using Amvar.Launcher.Core.Abstractions;
using Amvar.Launcher.Core.Application;
using Amvar.Launcher.Core.Configuration;
using Amvar.Launcher.Core.Lifecycle;
using Amvar.Launcher.Core.Runtime;

namespace Amvar.Launcher.Core.Tests;

public sealed class CoordinatorTests
{
    [Fact]
    public async Task Managed_release_starts_absent_service_navigates_and_stops_owned_stack()
    {
        var fake = new Dependencies { Probe = ProbeKind.NotListening, CompleteStart = true };
        var coordinator = Create(fake);
        await coordinator.InitializeAsync(new() { ManageService = true }, new("release"));
        Assert.Equal(1, fake.Starts);
        Assert.Equal(1, coordinator.Snapshot.NavigationId);
        Assert.Equal(SessionManagementMode.ManagedFullStack, coordinator.Snapshot.Mode);
        coordinator.ReportNavigation(coordinator.Snapshot.NavigationId, true);
        Assert.Equal(BackendPhase.Connected, coordinator.Snapshot.Backend);
        Assert.True(await coordinator.RequestExitAsync());
        Assert.Equal(1, fake.Stops);
    }

    [Fact]
    public async Task ObserveOnly_never_probes_starts_or_stops_even_after_navigation_failure()
    {
        var fake = new Dependencies();
        var coordinator = Create(fake);
        await coordinator.InitializeAsync(new() { ManageService = false }, new("unused"));
        coordinator.ReportNavigation(coordinator.Snapshot.NavigationId, false);
        await coordinator.RetryAsync();
        Assert.True(await coordinator.RequestExitAsync());
        Assert.Equal(0, fake.Probes + fake.Starts + fake.Stops + fake.Observations);
        Assert.Equal(ApplicationPhase.ReadyToExit, coordinator.Snapshot.Application);
    }

    [Fact]
    public async Task Existing_external_full_stack_is_never_adopted()
    {
        var fake = new Dependencies { Phase = StackPhase.Running };
        var coordinator = Create(fake);
        await coordinator.InitializeAsync(new(), new("release"));
        Assert.Equal(1, coordinator.Snapshot.NavigationId);
        Assert.Equal(SessionManagementMode.ObserveOnly, coordinator.Snapshot.Mode);
        Assert.True(await coordinator.RequestExitAsync());
        Assert.Equal(0, fake.Starts + fake.Stops);
    }

    [Fact]
    public async Task Exit_during_creation_waits_for_registration_and_stops_once()
    {
        var fake = new Dependencies { Probe = ProbeKind.NotListening, BlockStart = true };
        var coordinator = Create(fake);
        var connecting = coordinator.InitializeAsync(new(), new("release"));
        await fake.Started.Task.WaitAsync(TimeSpan.FromSeconds(5));
        var exit = coordinator.RequestExitAsync();
        Assert.Same(exit, coordinator.RequestExitAsync());
        fake.AllowStart.TrySetResult();
        await connecting;
        Assert.True(await exit);
        Assert.Equal(1, fake.Starts);
        Assert.Equal(1, fake.Stops);
        Assert.Equal(0, coordinator.Snapshot.NavigationId);
    }

    [Fact]
    public async Task Stop_failure_remains_visible_and_can_be_retried()
    {
        var fake = new Dependencies { HasOwnedSession = true, Phase = StackPhase.Running, StopSuccess = false };
        var coordinator = Create(fake);
        await coordinator.InitializeAsync(new(), new("release"));
        Assert.False(await coordinator.RequestExitAsync());
        Assert.Equal(ApplicationPhase.ExitBlocked, coordinator.Snapshot.Application);
        fake.StopSuccess = true;
        Assert.True(await coordinator.RequestExitAsync());
        Assert.Equal(2, fake.Stops);
    }

    [Fact]
    public async Task Old_navigation_completion_does_not_resurrect_an_exiting_app()
    {
        var coordinator = Create(new());
        await coordinator.InitializeAsync(new() { ManageService = false }, new("unused"));
        var navigation = coordinator.Snapshot.NavigationId;
        await coordinator.RequestExitAsync();
        coordinator.ReportNavigation(navigation, true);
        Assert.Equal(ApplicationPhase.ReadyToExit, coordinator.Snapshot.Application);
        Assert.NotEqual(BackendPhase.Connected, coordinator.Snapshot.Backend);
    }

    [Fact]
    public async Task Ambiguous_http_failure_does_not_start_a_second_stack()
    {
        var fake = new Dependencies { Probe = ProbeKind.Unavailable };
        var coordinator = Create(fake);
        await coordinator.InitializeAsync(new(), new("release"));
        Assert.Equal(BackendPhase.Faulted, coordinator.Snapshot.Backend);
        Assert.Equal(0, fake.Starts);
    }

    private static LauncherCoordinator Create(Dependencies fake) => new(
        new BackendSessionController(fake, fake, TimeProvider.System), fake);

    [Fact]
    public async Task Timeout_retry_continues_the_existing_creation()
    {
        var fake = new Dependencies { Probe = ProbeKind.NotListening };
        var coordinator = new LauncherCoordinator(new BackendSessionController(fake, fake, new ExpiringClock()), fake);
        await coordinator.InitializeAsync(new() { StartupTimeout = TimeSpan.FromSeconds(5) }, new("release"));
        Assert.True(coordinator.Snapshot.WaitExpired);
        await coordinator.RetryAsync();
        Assert.Equal(1, fake.Starts);
        Assert.Equal(0, coordinator.Snapshot.NavigationId);
        Assert.True(await coordinator.RequestExitAsync());
    }
    private sealed class ExpiringClock : TimeProvider
    {
        private long ticks;
        public override long TimestampFrequency => 1;
        public override long GetTimestamp() => Interlocked.Add(ref ticks, 10);
    }

    private sealed class Dependencies : IServiceProbe, IStackController, ILauncherLog
    {
        public bool HasOwnedSession { get; set; }
        public bool BlockStart { get; init; }
        public bool CompleteStart { get; init; }
        public bool StopSuccess { get; set; } = true;
        public int Probes, Starts, Stops, Observations;
        public ProbeKind Probe { get; set; } = ProbeKind.Available;
        public StackPhase Phase { get; set; } = StackPhase.Absent;
        public TaskCompletionSource Started { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
        public TaskCompletionSource AllowStart { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
        public Task<ServiceProbeResult> ProbeAsync(CancellationToken token) { Probes++; return Task.FromResult(new ServiceProbeResult(Probe)); }
        public Task<StackObservation> ObserveAsync(ProjectInstallation installation, CancellationToken token)
        { Observations++; return Task.FromResult(new StackObservation(Phase)); }
        public async Task StartAsync(ProjectInstallation installation, CancellationToken token)
        {
            Starts++;
            Started.TrySetResult();
            if (BlockStart) await AllowStart.Task;
            HasOwnedSession = true;
            Phase = CompleteStart ? StackPhase.Running : StackPhase.Starting;
            if (CompleteStart) Probe = ProbeKind.Available;
        }
        public Task<StackStopResult> StopAsync(CancellationToken token)
        { Stops++; return Task.FromResult(new StackStopResult(StopSuccess, "测试停止失败")); }
        public void Write(string message, Exception? exception = null) { }
    }
}
