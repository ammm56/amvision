using Amvar.Launcher.Core.Lifecycle;
using Amvar.Launcher.Desktop.Services;
using Amvar.Launcher.Desktop.ViewModels;

namespace Amvar.Launcher.Desktop.Tests;

public sealed class ViewPoliciesTests
{
    [Theory]
    [InlineData("http://127.0.0.1:5600/workflows", true)]
    [InlineData("https://127.0.0.1:5600", false)]
    [InlineData("http://127.0.0.1:5601", false)]
    [InlineData("http://127.0.0.1.example.com:5600", false)]
    [InlineData("file:///C:/windows", false)]
    [InlineData("/workflows", false)]
    public void Navigation_stays_in_configured_origin(string url, bool expected) =>
        Assert.Equal(expected, WebViewSession.IsLocal(new Uri(url, UriKind.RelativeOrAbsolute)));

    [Fact]
    public void Exit_failure_offers_retry_without_showing_webview()
    {
        var view = new LauncherViewModel();
        view.Apply(new() { Application = ApplicationPhase.ExitBlocked, Backend = BackendPhase.StopFailed, Problem = "timeout" });
        Assert.True(view.CanRetry); Assert.False(view.ShowBrowser); Assert.False(view.Busy);
    }
    [Fact]
    public void Startup_timeout_keeps_waiting_state_visible()
    {
        var view = new LauncherViewModel();
        view.Apply(new() { Application = ApplicationPhase.Active, Backend = BackendPhase.Starting, WaitExpired = true });
        Assert.Equal("服务仍在启动", view.Heading); Assert.True(view.CanRetry); Assert.False(view.ShowBrowser);
    }
}
