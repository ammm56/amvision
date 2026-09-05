import { describe, expect, it } from 'vitest'
import { matchesRuntimePreview, type RuntimePreviewFrame, type RuntimePreviewSnapshot } from './useRuntimePreview'

describe('runtime preview identity', () => {
  const snapshot = { workflow_runtime_id: 'runtime', workflow_runtime_revision_id: 'revision', workflow_app_version_id: 'version', runtime_generation: 3, worker_instance_id: 'worker', snapshot_fingerprint: 'hash' } as RuntimePreviewSnapshot
  const frame = { ...snapshot, format_id: 'amvision.workflow-runtime-preview.v1', workflow_run_id: 'run', sequence: 5, displays: [] } as unknown as RuntimePreviewFrame
  it('accepts only this actual worker and newer run', () => {
    expect(matchesRuntimePreview(snapshot, frame, 4)).toBe(true)
    expect(matchesRuntimePreview(snapshot, frame, 5)).toBe(false)
    for (const key of ['workflow_runtime_id', 'workflow_runtime_revision_id', 'workflow_app_version_id', 'worker_instance_id', 'snapshot_fingerprint']) {
      expect(matchesRuntimePreview(snapshot, { ...frame, [key]: 'old' }, 4)).toBe(false)
    }
    expect(matchesRuntimePreview(snapshot, { ...frame, runtime_generation: 2 }, 4)).toBe(false)
  })
})
