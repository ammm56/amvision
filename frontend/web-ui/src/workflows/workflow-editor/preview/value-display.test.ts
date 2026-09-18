import { describe, expect, it } from 'vitest'
import { appearanceStyles, displayFields, fieldValueColor, formatDisplayField, samePresentationContext } from './value-display'
import { readWorkflowAppModeConfig, writeWorkflowAppModeConfig } from '../app-mode/workflow-app-mode'

describe('Value Display contracts', () => {
  it('uses exact state colors ahead of field defaults without coloring null as a state', () => {
    const field = displayFields({ fields: [{ label: 'Result', value: 'custom', format: 'status', states: { custom: '#123456', null: '#FF0000' }, value_color: '#ABCDEF', label_color: '#654321' }] })[0]!
    expect(fieldValueColor(field)).toBe('#123456')
    expect(fieldValueColor({ ...field, value: 'Custom' })).toBe('#ABCDEF')
    expect(fieldValueColor({ ...field, value: null })).toBe('#ABCDEF')
    expect(field.labelColor).toBe('#654321')
    expect(formatDisplayField(field)).toBe('custom')
  })
  it('ignores invalid CSS and sizes while retaining valid opacity endpoints', () => {
    expect(appearanceStyles({ font_size: 24, panel_height: null, panel_width: 0, background_color: 'url(x)', background_opacity: 0 })).toEqual({ '--display-font-size': '24px', '--display-background-opacity': '0%' })
    expect(appearanceStyles({ font_size: true, status_font_size: Infinity, background_opacity: 100 })).toEqual({ '--display-background-opacity': '100%' })
    expect(appearanceStyles(undefined)).toEqual({})
  })
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
