using System;
using Amvision.Workflows.Examples.Net461Console.Model;

namespace Amvision.Workflows.Examples.Net461Console.Tools;

internal static class ExampleConfigStore
{
    private static readonly object SyncRoot = new object();
    private static ExampleConfig? current;

    public static ExampleConfig Current
    {
        get
        {
            var config = current;
            if (config is null)
            {
                throw new InvalidOperationException("Example config has not been initialized.");
            }

            return config;
        }
    }

    public static void Initialize(ExampleConfig config)
    {
        if (config is null)
        {
            throw new ArgumentNullException(nameof(config));
        }

        config.Validate();
        lock (SyncRoot)
        {
            current = config;
        }
    }
}
