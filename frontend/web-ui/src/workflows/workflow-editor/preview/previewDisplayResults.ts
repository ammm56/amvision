import { apiRequest } from '@/shared/api/http-client'
import { getWorkflowPreviewRun } from '../services/workflow-runtime.service'
import type { WorkflowJsonObject, WorkflowPreviewRun } from '../types'

interface DisplayDescriptor {
  display_id: string
  node_id: string
  node_type_id: string
  output_port: string
  duration_ms: number
  error: string | null
}
interface DisplayManifest {
  format_id: string
  preview_run_id: string
  displays: DisplayDescriptor[]
  legacy?: boolean
  error?: string | null
}

/** 终态只加载显示端口，避免反复搬运整个图的中间输出。 */
export async function loadPreviewDisplayResult(run: WorkflowPreviewRun, signal: AbortSignal) {
  const path = `/workflows/preview-runs/${encodeURIComponent(run.preview_run_id)}/displays`
  const manifest = await apiRequest<DisplayManifest>(path, { signal })
  if (manifest.format_id !== 'amvision.workflow-preview-displays.v1' || manifest.preview_run_id !== run.preview_run_id) {
    throw new Error('Invalid preview display result identity')
  }
  if (manifest.legacy) return { run: await getWorkflowPreviewRun(run.preview_run_id), errors: [] as string[] }
  const records = [...(run.node_records ?? [])]
  // 只替换显示端口，保留原记录的耗时与顺序；不能追加同节点记录导致耗时重复统计。
  for (const item of manifest.displays) {
    for (let index = 0; index < records.length; index++) {
      const record = records[index]!
      if (record.node_id !== item.node_id) continue
      const outputs = readOutputMapping(record.outputs)
      delete outputs[item.output_port]
      records[index] = { ...record, outputs }
    }
  }
  const errors: string[] = manifest.error ? [manifest.error] : []
  let outputs = run.outputs
  let templateOutputs = run.template_outputs
  if (run.state === 'succeeded') {
    try {
      const result = await apiRequest<{ outputs: WorkflowJsonObject; template_outputs: WorkflowJsonObject }>(
        `/workflows/preview-runs/${encodeURIComponent(run.preview_run_id)}/display-outputs`, { signal })
      outputs = result.outputs
      templateOutputs = result.template_outputs
    } catch (error) {
      if (signal.aborted) throw error
      errors.push(error instanceof Error ? error.message : String(error))
    }
  }
  let nextIndex = 0
  await Promise.all(Array.from({ length: Math.min(4, manifest.displays.length) }, async () => {
    while (nextIndex < manifest.displays.length && !signal.aborted) {
      const item = manifest.displays[nextIndex++]!
      try {
        if (item.error) throw new Error(item.error)
        const payload = await apiRequest<WorkflowJsonObject>(`${path}/${encodeURIComponent(item.display_id)}`, { signal })
        let index = records.length - 1
        while (index >= 0 && records[index]!.node_id !== item.node_id) index--
        if (index >= 0) records[index] = { ...records[index]!, outputs: { ...readOutputMapping(records[index]!.outputs), [item.output_port]: payload } }
        else records.push({ node_id: item.node_id, node_type_id: item.node_type_id,
          duration_ms: item.duration_ms, outputs: { [item.output_port]: payload }, inputs: {}, runtime_kind: '' })
      } catch (error) {
        if (signal.aborted) throw error
        errors.push(`${item.node_id}: ${error instanceof Error ? error.message : String(error)}`)
      }
    }
  }))
  signal.throwIfAborted()
  return { run: { ...run, outputs, template_outputs: templateOutputs, node_records: records }, errors }
}

function readOutputMapping(value: unknown): WorkflowJsonObject {
  return value !== null && typeof value === 'object' && !Array.isArray(value) ? { ...value as WorkflowJsonObject } : {}
}
