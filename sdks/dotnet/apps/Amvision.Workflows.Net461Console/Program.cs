using System;
using System.Threading;
using System.Threading.Tasks;

namespace Amvision.Workflows.Net461Console;

/// <summary>
/// 控制台程序入口，负责加载配置并执行代码中手动指定的调用方法。
/// </summary>
internal static class Program
{
    /// <summary>
    /// 默认 runtime 配置 key；现场使用时按 Config/config_*.json 修改。
    /// </summary>
    private const string RuntimeName = "yolo11m_barqrcode_runtime";

    /// <summary>
    /// 默认 TriggerSource 配置 key；现场使用时按 Config/config_*.json 修改。
    /// </summary>
    private const string TriggerSourceName = "yolo11m_barqrcode_zeromq";

    /// <summary>
    /// ZeroMQ 图片文件路径；调用 InvokeZeroMqImageFromFileAsync 时填写。
    /// </summary>
    private const string ZeroMqImagePath = "";

    /// <summary>
    /// 同步入口，桥接 async 主流程并统一输出错误。
    /// </summary>
    /// <returns>进程退出码。</returns>
    private static int Main()
    {
        try
        {
            MainAsync(CancellationToken.None).GetAwaiter().GetResult();
            return 0;
        }
        catch (Exception exception)
        {
            Console.Error.WriteLine(exception);
            return 1;
        }
    }

    /// <summary>
    /// 主执行流程；启动时加载全部 config_*.json，并调用代码中明确指定的方法。
    /// </summary>
    /// <param name="cancellationToken">取消信号。</param>
    private static async Task MainAsync(CancellationToken cancellationToken)
    {
        using var runner = WorkflowOperationRunner.CreateDefault();
        PrintLoadedConfigs(runner);
        await RunSelectedMethodAsync(runner, cancellationToken).ConfigureAwait(false);
    }

    /// <summary>
    /// 手动选择要执行的方法；现场调试或接入 WinForms/WPF 时，只需要改这里的调用行。
    /// </summary>
    /// <param name="runner">封装后的 Workflow 调用入口。</param>
    /// <param name="cancellationToken">取消信号。</param>
    private static Task RunSelectedMethodAsync(
        WorkflowOperationRunner runner,
        CancellationToken cancellationToken)
    {
        return runner.GetRuntimeHealthAsync(RuntimeName, cancellationToken);

        // return runner.GetRuntimeAsync(RuntimeName, cancellationToken);
        // return runner.ListProjectRuntimesAsync(RuntimeName, cancellationToken);
        // return runner.StartRuntimeAsync(RuntimeName, cancellationToken);
        // return runner.StopRuntimeAsync(RuntimeName, cancellationToken);
        // return runner.RestartRuntimeAsync(RuntimeName, cancellationToken);
        // return runner.ListRuntimeInstancesAsync(RuntimeName, cancellationToken);
        // return runner.InvokeRuntimeAppResultAsync(RuntimeName, cancellationToken);
        // return runner.RunRuntimeAsync(RuntimeName, cancellationToken);
        // return runner.CheckRuntimeFlowAsync(RuntimeName, cancellationToken);
        // return runner.GetRuntimeEventsAsync(RuntimeName, cancellationToken);
        // return runner.ListTriggerSourcesAsync(RuntimeName, cancellationToken);
        // return runner.GetTriggerSourceAsync(TriggerSourceName, cancellationToken);
        // return runner.EnableTriggerSourceAsync(TriggerSourceName, cancellationToken);
        // return runner.DisableTriggerSourceAsync(TriggerSourceName, cancellationToken);
        // return runner.GetTriggerSourceHealthAsync(TriggerSourceName, cancellationToken);
        // return runner.InvokeZeroMqEventAsync(TriggerSourceName, cancellationToken: cancellationToken);
        // return runner.InvokeZeroMqConfiguredImageAsync(TriggerSourceName, cancellationToken);
        // return runner.InvokeZeroMqImageFromFileAsync(TriggerSourceName, ZeroMqImagePath, cancellationToken: cancellationToken);
    }

    /// <summary>
    /// 打印已加载的 runtime key 和 TriggerSource key，便于现场确认调用目标。
    /// </summary>
    /// <param name="runner">封装后的 Workflow 调用入口。</param>
    private static void PrintLoadedConfigs(WorkflowOperationRunner runner)
    {
        Console.WriteLine("Loaded runtime config keys:");
        foreach (var key in runner.RuntimeNames)
        {
            Console.WriteLine($"  runtime: {key}");
        }

        Console.WriteLine("Loaded TriggerSource config keys:");
        foreach (var key in runner.TriggerSourceNames)
        {
            Console.WriteLine($"  trigger_source: {key}");
        }
    }
}
