using System;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using Amvision.Workflows;
using Amvision.Workflows.Net461Console.Model;
using Amvision.Workflows.Net461Console.Tools;
using Amvision.Workflows.Net461Console.Runtime;
using Amvision.Workflows.Net461Console.TriggerSource;
using Amvision.Workflows.Net461Console.TriggerSource.ZeroMQ;

namespace Amvision.Workflows.Net461Console;

/// <summary>
/// 控制台程序入口，负责加载配置、初始化 SDK client，并按命令分发到 Runtime 或 TriggerSource 操作。
/// </summary>
internal static class Program
{
    /// <summary>
    /// 同步入口，桥接 async 主流程并统一输出错误。
    /// </summary>
    /// <param name="args">命令行参数。</param>
    /// <returns>进程退出码。</returns>
    private static int Main(string[] args)
    {
        _ = args;
        try
        {
            MainAsync(args, CancellationToken.None).GetAwaiter().GetResult();
            return 0;
        }
        catch (Exception exception)
        {
            Console.Error.WriteLine(exception);
            PrintUsage();
            return 1;
        }
    }

    /// <summary>
    /// 主执行流程；无命令时只打印可用 key 和命令说明，不执行任何现场动作。
    /// </summary>
    /// <param name="args">命令行参数。</param>
    /// <param name="cancellationToken">取消信号。</param>
    private static async Task MainAsync(string[] args, CancellationToken cancellationToken)
    {
        var catalog = WorkflowConfigLoader.LoadDefault();
        WorkflowConfigStore.Initialize(catalog);
        PrintLoadedConfigs(catalog);

        using var client = new AmvisionWorkflowClient(new AmvisionWorkflowClientOptions
        {
            BaseApiUrl = catalog.DefaultBackend.BaseApiUrl,
            AccessToken = catalog.DefaultBackend.AccessToken,
            Timeout = TimeSpan.FromSeconds(catalog.DefaultBackend.HttpTimeoutSeconds)
        });

        if (args.Length == 0)
        {
            PrintUsage();
            return;
        }

        var runtimeOperations = new WorkflowRuntimeOperations(client, catalog);
        var triggerSourceOperations = new WorkflowTriggerSourceOperations(client, catalog);
        var zeroMqOperations = new ZeroMqTriggerOperations(catalog);

        var command = args[0].Trim().ToLowerInvariant();
        switch (command)
        {
            case "runtime-use":
                await runtimeOperations.RunRuntimeUsageFlowAsync(ResolveRuntimeName(catalog, args), cancellationToken).ConfigureAwait(false);
                break;
            case "runtime-list":
                await runtimeOperations.ListProjectRuntimesAsync(ResolveRuntimeName(catalog, args), cancellationToken).ConfigureAwait(false);
                break;
            case "runtime-start":
                await runtimeOperations.StartRuntimeAsync(ResolveRuntimeName(catalog, args), cancellationToken).ConfigureAwait(false);
                break;
            case "runtime-stop":
                await runtimeOperations.StopRuntimeAsync(ResolveRuntimeName(catalog, args), cancellationToken).ConfigureAwait(false);
                break;
            case "runtime-restart":
                await runtimeOperations.RestartRuntimeAsync(ResolveRuntimeName(catalog, args), cancellationToken).ConfigureAwait(false);
                break;
            case "runtime-health":
                await runtimeOperations.GetRuntimeHealthAsync(ResolveRuntimeName(catalog, args), cancellationToken).ConfigureAwait(false);
                break;
            case "runtime-instances":
                await runtimeOperations.ListRuntimeInstancesAsync(ResolveRuntimeName(catalog, args), cancellationToken).ConfigureAwait(false);
                break;
            case "runtime-invoke":
                await runtimeOperations.InvokeRuntimeAppResultAsync(ResolveRuntimeName(catalog, args), cancellationToken).ConfigureAwait(false);
                break;
            case "runtime-submit-run":
                await runtimeOperations.SubmitWorkflowRunAsync(ResolveRuntimeName(catalog, args), cancellationToken).ConfigureAwait(false);
                break;
            case "runtime-events":
                await runtimeOperations.GetRuntimeEventsAsync(ResolveRuntimeName(catalog, args), cancellationToken).ConfigureAwait(false);
                break;
            case "triggersource-list":
                await triggerSourceOperations.ListTriggerSourcesAsync(ResolveRuntimeName(catalog, args), cancellationToken).ConfigureAwait(false);
                break;
            case "triggersource-get":
                await triggerSourceOperations.GetTriggerSourceAsync(ResolveTriggerSourceName(catalog, args), cancellationToken).ConfigureAwait(false);
                break;
            case "triggersource-enable":
                await triggerSourceOperations.EnableTriggerSourceAsync(ResolveTriggerSourceName(catalog, args), cancellationToken).ConfigureAwait(false);
                break;
            case "triggersource-disable":
                await triggerSourceOperations.DisableTriggerSourceAsync(ResolveTriggerSourceName(catalog, args), cancellationToken).ConfigureAwait(false);
                break;
            case "triggersource-health":
                await triggerSourceOperations.GetTriggerSourceHealthAsync(ResolveTriggerSourceName(catalog, args), cancellationToken).ConfigureAwait(false);
                break;
            case "zeromq-event":
                await zeroMqOperations.InvokeEventAsync(ResolveTriggerSourceName(catalog, args), cancellationToken: cancellationToken).ConfigureAwait(false);
                break;
            case "zeromq-image":
                await InvokeZeroMqImageAsync(zeroMqOperations, catalog, args, cancellationToken).ConfigureAwait(false);
                break;
            default:
                throw new InvalidOperationException($"Unknown command: {command}");
        }
    }

    /// <summary>
    /// 输出可用命令和配置文件约定。
    /// </summary>
    private static void PrintUsage()
    {
        Console.Error.WriteLine();
        Console.Error.WriteLine("Usage:");
        Console.Error.WriteLine("  runtime-use [runtime_key]");
        Console.Error.WriteLine("  runtime-list|runtime-start|runtime-stop|runtime-restart|runtime-health|runtime-instances|runtime-invoke|runtime-submit-run|runtime-events [runtime_key]");
        Console.Error.WriteLine("  triggersource-list [runtime_key]");
        Console.Error.WriteLine("  triggersource-get|triggersource-enable|triggersource-disable|triggersource-health [trigger_source_key]");
        Console.Error.WriteLine("  zeromq-event [trigger_source_key]");
        Console.Error.WriteLine("  zeromq-image [trigger_source_key] [image_path]");
        Console.Error.WriteLine();
        Console.Error.WriteLine("Config files are loaded from Config/config_*.json.");
    }

    /// <summary>
    /// 打印已加载的 runtime key 和 TriggerSource key，便于现场确认调用目标。
    /// </summary>
    /// <param name="catalog">已加载的配置 catalog。</param>
    private static void PrintLoadedConfigs(WorkflowConfigurationCatalog catalog)
    {
        Console.WriteLine("Loaded runtime config keys:");
        foreach (var key in catalog.Runtimes.Keys)
        {
            Console.WriteLine($"  runtime: {key}");
        }

        Console.WriteLine("Loaded TriggerSource config keys:");
        foreach (var key in catalog.TriggerSources.Keys)
        {
            Console.WriteLine($"  trigger_source: {key}");
        }
    }

    /// <summary>
    /// 从命令行解析 runtime key；未传入时使用第一个配置项作为默认值。
    /// </summary>
    /// <param name="catalog">配置 catalog。</param>
    /// <param name="args">命令行参数。</param>
    /// <returns>runtime key。</returns>
    private static string ResolveRuntimeName(WorkflowConfigurationCatalog catalog, string[] args)
    {
        if (args.Length > 1 && !string.IsNullOrWhiteSpace(args[1]))
        {
            return args[1];
        }

        return catalog.Runtimes.Keys.First();
    }

    /// <summary>
    /// 从命令行解析 TriggerSource key；未传入时使用第一个配置项作为默认值。
    /// </summary>
    /// <param name="catalog">配置 catalog。</param>
    /// <param name="args">命令行参数。</param>
    /// <returns>TriggerSource key。</returns>
    private static string ResolveTriggerSourceName(WorkflowConfigurationCatalog catalog, string[] args)
    {
        if (args.Length > 1 && !string.IsNullOrWhiteSpace(args[1]))
        {
            return args[1];
        }

        return catalog.TriggerSources.Keys.First();
    }

    /// <summary>
    /// 执行 ZeroMQ 图片触发；命令行给出图片路径时优先使用该路径，否则使用配置中的 image_path。
    /// </summary>
    /// <param name="zeroMqOperations">ZeroMQ 触发操作对象。</param>
    /// <param name="catalog">配置 catalog。</param>
    /// <param name="args">命令行参数。</param>
    /// <param name="cancellationToken">取消信号。</param>
    /// <returns>TriggerSource 调用结果。</returns>
    private static Task<TriggerResult> InvokeZeroMqImageAsync(
        ZeroMqTriggerOperations zeroMqOperations,
        WorkflowConfigurationCatalog catalog,
        string[] args,
        CancellationToken cancellationToken)
    {
        var triggerSourceName = ResolveTriggerSourceName(catalog, args);
        if (args.Length > 2 && !string.IsNullOrWhiteSpace(args[2]))
        {
            return zeroMqOperations.InvokeImageFromFileAsync(
                triggerSourceName,
                args[2],
                mediaType: null,
                cancellationToken);
        }

        return zeroMqOperations.InvokeConfiguredImageAsync(triggerSourceName, cancellationToken);
    }
}
