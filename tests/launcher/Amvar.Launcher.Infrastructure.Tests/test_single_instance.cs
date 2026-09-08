using Amvar.Launcher.Infrastructure.Processes;

namespace Amvar.Launcher.Infrastructure.Tests;

public sealed class SingleInstanceTests
{
    [Fact]
    public async Task Second_instance_activates_first_and_lease_is_reusable()
    {
        var installation = Path.Combine(AppContext.BaseDirectory, "instance-" + Guid.NewGuid().ToString("N"));
        var activated = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        using (var first = await SingleInstanceLease.AcquireAsync(installation, installation))
        {
            Assert.NotNull(first);
            first.Listen(() => activated.TrySetResult());
            Assert.Null(await SingleInstanceLease.AcquireAsync(installation, installation));
            await activated.Task.WaitAsync(TimeSpan.FromSeconds(5));
        }
        using var third = await SingleInstanceLease.AcquireAsync(installation, installation);
        Assert.NotNull(third);
    }
}
