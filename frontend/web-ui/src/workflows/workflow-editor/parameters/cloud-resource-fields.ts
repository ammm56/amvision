import type { NodeParameterUiField, WorkflowJsonObject } from '../types'

/** 多行三维来源/保存控件与画布使用相同固定高度，不依赖当前资源 ID 长度。 */
export function cloudResourceFieldHeight(schema: Record<string, unknown>): number | null {
  if (schema['x-ui-widget'] === 'cloud-source') return 104
  if (schema['x-ui-widget'] === 'cloud-target') return 168
  return null
}

/** 沿用资产来源声明的互斥字段；不隐藏其他节点参数或修改已保存数据。 */
export function visibleCloudParameterFields(fields: NodeParameterUiField[], parameters: WorkflowJsonObject): NodeParameterUiField[] {
  const excluded = new Set<string>()
  for (const field of fields) {
    const value = parameters[field.parameter_name]
    if (field.json_schema['x-ui-widget'] !== 'cloud-source' || !value || typeof value !== 'object' || Array.isArray(value) || (value as Record<string, unknown>).kind !== 'asset') continue
    const names = field.json_schema['x-asset-clears']
    if (Array.isArray(names)) for (const name of names) if (typeof name === 'string') excluded.add(name)
  }
  return fields.filter(field => !field.hidden && !excluded.has(field.parameter_name))
}
