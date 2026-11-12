import type { ViewerImageInteractionTool } from './normalizeImageInteractionTool'

/** 同一种绘图工具可以分别绑定列、行参数，不能按工具类型混为同一个按钮。 */
export function interactionToolKey(tool: ViewerImageInteractionTool): string {
  return JSON.stringify([tool.tool, tool.targetParameters])
}

/** 从明确选定的行或列工具读取有向位移；保留负方向和非正交分量。 */
export function arrayStepUpdates(targets: string[], line: [number, number, number, number]): Record<string, unknown> | null {
  const dx = Math.round((line[2] - line[0]) * 1000) / 1000
  const dy = Math.round((line[3] - line[1]) * 1000) / 1000
  if (![dx, dy].every(Number.isFinite) || Math.hypot(dx, dy) < 1e-8) return null
  if (targets.includes('column_step_xy')) return { column_step_xy: [dx, dy] }
  if (targets.includes('row_step_xy')) return { row_step_xy: [dx, dy] }
  if (targets.includes('step_x') && targets.includes('column_step_y')) return { step_x: dx, column_step_y: dy }
  if (targets.includes('row_step_x') && targets.includes('step_y')) return { row_step_x: dx, step_y: dy }
  return null
}
