export interface ViewerImageInteractionTool {
  tool: string
  label?: string | null
  targetParameters: string[]
  clearParameters?: string[]
  minPoints?: number | null
  maxPoints?: number | null
  angleToleranceDeg?: number | null
  searchPaddingRatio?: number | null
  searchPaddingMin?: number | null
  applyParameters?: Record<string, unknown>
  brushSize?: number | null
  maskObjectKey?: string | null
  sourceIdentity?: string | null
  maskSrc?: string | null
}

/**
 * 规范化交互工具的公共字段，同时保留 Mask 等工具的专属能力。
 */
export function normalizeImageInteractionTool(
  toolItem: ViewerImageInteractionTool,
  options: {
    isSupported: (tool: string) => boolean
    fallbackLabel: (tool: string) => string
  },
): ViewerImageInteractionTool[] {
  if (
    !options.isSupported(toolItem.tool)
    || toolItem.targetParameters.length === 0
  ) return []
  return [{
    ...toolItem,
    label: toolItem.label ?? options.fallbackLabel(toolItem.tool),
    clearParameters: toolItem.clearParameters ?? [],
    minPoints: toolItem.minPoints ?? null,
    maxPoints: toolItem.maxPoints ?? null,
    angleToleranceDeg: toolItem.angleToleranceDeg ?? null,
    searchPaddingRatio: toolItem.searchPaddingRatio ?? null,
    searchPaddingMin: toolItem.searchPaddingMin ?? null,
  }]
}
