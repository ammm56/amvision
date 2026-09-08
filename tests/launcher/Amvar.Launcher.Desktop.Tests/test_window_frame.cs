using Avalonia;
using Amvar.Launcher.Desktop.Services;
using Xunit;

namespace Amvar.Launcher.Desktop.Tests;

public sealed class WindowFrameTests
{
    [Theory]
    [InlineData(1, 400, 10)]
    [InlineData(1279, 400, 11)]
    [InlineData(600, 1, 12)]
    [InlineData(600, 799, 15)]
    [InlineData(1, 1, 13)]
    [InlineData(1279, 1, 14)]
    [InlineData(1, 799, 16)]
    [InlineData(1279, 799, 17)]
    [InlineData(12, 1, 13)]
    [InlineData(1, 12, 13)]
    [InlineData(16, 1, 12)]
    [InlineData(12, 12, 0)]
    [InlineData(5, 5, 0)]
    [InlineData(640, 400, 0)]
    [InlineData(-1, 10, 0)]
    [InlineData(1280, 10, 0)]
    public void Native_hit_test_separates_eight_edges_from_interactive_content(double x, double y, int expected) =>
        Assert.Equal(expected, WindowsWindowFrame.ResizeHitTest(new Point(x, y), new Size(1280, 800)));
}
