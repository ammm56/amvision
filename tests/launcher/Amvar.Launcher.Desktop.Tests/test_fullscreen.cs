using Avalonia.Controls;
using Avalonia.Headless;
using Avalonia.Input;
using Amvar.Launcher.Desktop.Services;
using Amvar.Launcher.Desktop.Views;

namespace Amvar.Launcher.Desktop.Tests;

[Collection("Avalonia UI")]
public sealed class FullscreenTests
{
    [Fact]
    public async Task F11_ignores_modifiers_and_repeat_then_restores_shell()
    {
        using var session = HeadlessUnitTestSession.StartNew(typeof(NativeViewTests.TestApplication));
        await session.Dispatch(() =>
        {
            var window = new MainWindow();
            window.Show();
            void Press(KeyModifiers modifiers = KeyModifiers.None) => window.RaiseEvent(new KeyEventArgs
                { RoutedEvent = InputElement.KeyDownEvent, Key = Key.F11, KeyModifiers = modifiers });
            Press(KeyModifiers.Control);
            Assert.Equal(WindowState.Normal, window.WindowState);
            Press();
            Assert.Equal(WindowState.FullScreen, window.WindowState);
            Assert.False(window.FindControl<Border>("TitleBar")!.IsVisible);
            Press();
            Assert.Equal(WindowState.FullScreen, window.WindowState);
            window.RaiseEvent(new KeyEventArgs { RoutedEvent = InputElement.KeyUpEvent, Key = Key.F11 });
            Press();
            Assert.Equal(WindowState.Normal, window.WindowState);
            Assert.True(window.FindControl<Border>("TitleBar")!.IsVisible);
            Assert.True(window.FindControl<Border>("StatusBar")!.IsVisible);
            window.Close();
        }, CancellationToken.None);
    }

    [Theory]
    [InlineData(WindowState.Normal)]
    [InlineData(WindowState.Maximized)]
    public void Exit_restores_previous_window_state(WindowState original)
    {
        var controller = new FullscreenController();
        Assert.Equal(WindowState.FullScreen, controller.Toggle(original));
        Assert.True(controller.IsFullscreen);
        Assert.Equal(original == WindowState.Maximized, controller.RestoreMaximized);
        Assert.Equal(original, controller.Toggle(WindowState.FullScreen));
        Assert.False(controller.IsFullscreen);
    }
}
