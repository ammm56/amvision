import type { WorkflowJsonObject } from '../types'

/** 把 for-each 单轮调用 id 还原为画布中的原始 node_id。 */
function readCanvasNodeId(nodeId: string): string {
  const scopedNodeMatch = nodeId.match(/^.*\[\d+\]\.(.+)$/)
  return scopedNodeMatch?.[1] || nodeId
}

/** 按画布 node_id 保留一次 Preview 中每个节点最后一轮的执行耗时。 */
export function buildPreviewNodeDurationIndex(
  nodeRecords: WorkflowJsonObject[],
): ReadonlyMap<string, number> {
  const durations = new Map<string, number>()
  for (const record of nodeRecords) {
    const nodeId = record.node_id
    const durationMs = record.duration_ms
    if (typeof nodeId !== 'string' || !nodeId.trim()) continue
    if (typeof durationMs !== 'number' || !Number.isFinite(durationMs) || durationMs < 0) continue
    durations.set(readCanvasNodeId(nodeId.trim()), durationMs)
  }
  return durations
}

/** 把节点耗时格式化为画布角标使用的一位小数文本。 */
export function formatPreviewNodeDuration(durationMs: number): string {
  return `${durationMs.toFixed(1)} ms`
}
