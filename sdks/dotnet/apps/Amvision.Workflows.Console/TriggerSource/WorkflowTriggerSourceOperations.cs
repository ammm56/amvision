using System;
using Amvision.Workflows.Console.Model;

namespace Amvision.Workflows.Console.TriggerSource;

/// <summary>
/// TriggerSource HTTP 管理操作集合。
/// </summary>
internal sealed partial class WorkflowTriggerSourceOperations
{
    /// <summary>
    /// 复用的 HTTP SDK client。
    /// </summary>
    private readonly AmvisionWorkflowClient client;

    /// <summary>
    /// runtime 和 TriggerSource 配置索引。
    /// </summary>
    private readonly WorkflowConfigurationCatalog catalog;

    /// <summary>
    /// 初始化 TriggerSource 管理操作对象。
    /// </summary>
    /// <param name="client">HTTP SDK client。</param>
    /// <param name="catalog">配置 catalog。</param>
    public WorkflowTriggerSourceOperations(AmvisionWorkflowClient client, WorkflowConfigurationCatalog catalog)
    {
        this.client = client ?? throw new ArgumentNullException(nameof(client));
        this.catalog = catalog ?? throw new ArgumentNullException(nameof(catalog));
    }

    /// <summary>
    /// 按 TriggerSource key 获取配置。
    /// </summary>
    /// <param name="triggerSourceName">TriggerSource key。</param>
    /// <returns>TriggerSource 配置。</returns>
    private ConfiguredTriggerSource GetConfiguredTriggerSource(string triggerSourceName)
    {
        return catalog.GetTriggerSource(triggerSourceName);
    }
}
