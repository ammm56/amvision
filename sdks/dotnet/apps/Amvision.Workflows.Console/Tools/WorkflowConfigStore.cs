using System;
using Amvision.Workflows.Console.Model;

namespace Amvision.Workflows.Console.Tools;

/// <summary>
/// 控制台程序内的配置单例，启动时载入一次，后续 runtime 和 TriggerSource 操作共享。
/// </summary>
internal static class WorkflowConfigStore
{
    /// <summary>
    /// 保护配置初始化过程，避免多线程同时写入。
    /// </summary>
    private static readonly object SyncRoot = new object();

    /// <summary>
    /// 当前已加载的配置 catalog。
    /// </summary>
    private static WorkflowConfigurationCatalog? current;

    /// <summary>
    /// 获取当前配置 catalog；未初始化时抛出明确错误。
    /// </summary>
    public static WorkflowConfigurationCatalog Current
    {
        get
        {
            var catalog = current;
            if (catalog is null)
            {
                throw new InvalidOperationException("Workflow config catalog has not been initialized.");
            }

            return catalog;
        }
    }

    /// <summary>
    /// 初始化配置单例。
    /// </summary>
    /// <param name="catalog">已加载并校验过的配置 catalog。</param>
    public static void Initialize(WorkflowConfigurationCatalog catalog)
    {
        if (catalog is null)
        {
            throw new ArgumentNullException(nameof(catalog));
        }

        lock (SyncRoot)
        {
            current = catalog;
        }
    }
}
