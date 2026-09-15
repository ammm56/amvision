import { describe, expect, it } from 'vitest'
import { formatDisplayField, samePresentationContext } from './value-display'
import { readWorkflowAppModeConfig, writeWorkflowAppModeConfig } from '../app-mode/workflow-app-mode'

describe('Value Display contracts', () => {
  it('formats once and preserves missing versus zero', () => {
    const field = { label: '良品率', value: .9583, format: 'percent', precision: 2, states: {} }
    expect(formatDisplayField(field)).toBe('95.83%')
    expect(formatDisplayField({ ...field, value: null })).toBe('—')
    expect(formatDisplayField({ ...field, value: 0 })).toBe('0.00%')
    expect(formatDisplayField({ ...field, format: 'integer', value: 9007199254740992 })).toBe('—')
  })
  it('does not pair images with different file generations or snapshots', () => {
    const context = { generation: 'file-a', sequence: 2, snapshot_revision: 'rev' }
    expect(samePresentationContext(context, { ...context })).toBe(true)
    expect(samePresentationContext(context, { ...context, generation: 'file-b' })).toBe(false)
    expect(samePresentationContext(context, { ...context, snapshot_revision: 'old' })).toBe(false)
    expect(samePresentationContext(null, null)).toBe(false)
  })
  it('round-trips optional overlay without duplicating field configuration', () => {
    const config = { format_id: 'amvision.workflow-app-mode.v1' as const, title: '', displays: [{
      node_id: 'image', output_port: 'body', title: '', size: 'medium' as const,
      overlay: { node_id: 'values', output_port: 'body', position: 'top-left' as const },
    }] }
    expect(readWorkflowAppModeConfig(writeWorkflowAppModeConfig({}, config))).toEqual(config)
  })
})
