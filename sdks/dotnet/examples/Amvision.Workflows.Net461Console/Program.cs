using System;
using System.Threading;
using System.Threading.Tasks;
using Amvision.Workflows;
using Amvision.Workflows.Examples.Net461Console.Tools;

namespace Amvision.Workflows.Examples.Net461Console;

internal static class Program
{
    private static int Main(string[] args)
    {
        _ = args;
        try
        {
            MainAsync(CancellationToken.None).GetAwaiter().GetResult();
            return 0;
        }
        catch (Exception exception)
        {
            Console.Error.WriteLine(exception);
            PrintUsage();
            return 1;
        }
    }

    private static async Task MainAsync(CancellationToken cancellationToken)
    {
        var config = ExampleConfigLoader.LoadDefault();
        ExampleConfigStore.Initialize(config);
        var backend = ExampleConfigStore.Current.Backend;

        using var client = new AmvisionWorkflowClient(new AmvisionWorkflowClientOptions
        {
            BaseApiUrl = backend.BaseApiUrl,
            AccessToken = backend.AccessToken,
            Timeout = TimeSpan.FromSeconds(backend.HttpTimeoutSeconds)
        });

        var example = new WorkflowRuntimeControlExample(client);
        await example.RunAsync(cancellationToken).ConfigureAwait(false);
    }

    private static void PrintUsage()
    {
        Console.Error.WriteLine();
        Console.Error.WriteLine("Edit config.json in the example project root before running.");
        Console.Error.WriteLine("Set either workflow_runtime.workflow_runtime_id to reuse a runtime");
        Console.Error.WriteLine("or workflow_runtime.application_id to create a runtime.");
    }
}
