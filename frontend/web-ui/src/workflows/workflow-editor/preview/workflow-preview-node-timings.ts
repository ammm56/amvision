import type { WorkflowJsonObject } from '../types'

/** 按画布 node_id 汇总一次 Preview 中同一节点的全部执行耗时。 */
export function buildPreviewNodeDurationIndex(
  nodeRecords: WorkflowJsonObject[],
): ReadonlyMap<string, number> {
  const durations = new Map<string, number>()
  for (const record of nodeRecords) {
    const nodeId = record.node_id
    const durationMs = record.duration_ms
    if (typeof nodeId !== 'string' || !nodeId.trim()) continue
    if (typeof durationMs !== 'number' || !Number.isFinite(durationMs) || durationMs < 0) continue
    durations.set(nodeId, (durations.get(nodeId) ?? 0) + durationMs)
  }
  return durations
}

/** 把节点耗时格式化为画布角标使用的一位小数文本。 */
export function formatPreviewNodeDuration(durationMs: number): string {
  return `${durationMs.toFixed(1)} ms`
}
