import { mount } from '@vue/test-utils'
import { expect, it } from 'vitest'
import { i18n } from '@/platform/i18n'
import WorkflowPreviewRunResultPanel from '@/workflows/workflow-editor/components/WorkflowPreviewRunResultPanel.vue'
import type { WorkflowPreviewRun } from '@/workflows/workflow-editor/types'

it('shows the failed asset node outside truncated JSON and clears the error when switching runs', async () => {
  const run: WorkflowPreviewRun = {
    format_id: 'amvision.workflow-preview-session.v1', preview_run_id: 'failed', session_id: 's',
    document_revision: 'd', project_id: 'p', application_id: 'a', state: 'failed', created_at: '2026-11-04T00:00:00Z',
    outputs: { data: 'x'.repeat(14000) }, node_records: [{ node_id: 'save', node_display_name: 'Save Cloud' }],
    error: { code: 'ResourceConflictError', message: '点云保存身份冲突或基版本已更新', details: { node_id: 'save' } },
  }
  const w = mount(WorkflowPreviewRunResultPanel, { global: { plugins: [i18n] }, props: { previewRun: run, badgeTone: 'danger', statusLabel: 'failed', createdAtText: '' } })
  expect(w.get('[role=alert]').text()).toContain('Save Cloud · ResourceConflictError')
  expect(w.get('[role=alert]').text()).toContain(run.error!.message)
  expect(w.get('pre').text()).not.toContain(run.error!.message)
  await w.setProps({ previewRun: { ...run, preview_run_id: 'next', state: 'accepted', node_records: [], error: null } })
  expect(w.find('[role=alert]').exists()).toBe(false)
  await w.setProps({ previewRun: { ...run, node_records: [], error: { code: 'invalid_request', message: '<img src=x onerror=alert(1)>', details: {} } } })
  expect(w.get('[role=alert]').text()).toContain('invalid_request')
  expect(w.get('[role=alert]').text()).toContain('<img src=x onerror=alert(1)>')
  expect(w.find('[role=alert] img').exists()).toBe(false)
  w.unmount()
})
