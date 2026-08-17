import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it } from 'vitest'

import { i18n, setI18nLocale } from '@/platform/i18n'
import WorkflowPreviewRunResultPanel from './WorkflowPreviewRunResultPanel.vue'

describe('WorkflowPreviewRunResultPanel', () => {
  beforeEach(() => setI18nLocale('zh-CN'))

  it('在属性面板直接显示完整 PreviewRun 原始 JSON', async () => {
    const previewRun = {
      format_id: 'amvision.workflow-preview-run.v1',
      preview_run_id: 'preview-run-1',
      project_id: 'project-1',
      application_id: 'app-1',
      source_kind: 'inline-snapshot',
      application_snapshot_object_key: 'application.json',
      template_snapshot_object_key: 'template.json',
      state: 'succeeded',
      created_at: '2026-08-17T00:00:00Z',
      timeout_seconds: 30,
      outputs: { result: { ok: true } },
      template_outputs: {},
      node_records: [{ node_id: 'node-1', duration_ms: 12.34 }],
      metadata: { timings: { graph_execute_ms: 12.34 } },
    }
    const wrapper = mount(WorkflowPreviewRunResultPanel, {
      global: { plugins: [i18n] },
      props: {
        previewRun,
        badgeTone: 'info',
        statusLabel: 'succeeded',
        createdAtText: '2026-08-17 08:00:00',
      },
    })

    const rawJson = wrapper.get('.workflow-graph-preview-result__raw-json')
    expect(rawJson.text()).toBe(JSON.stringify(previewRun, null, 2))
    expect(wrapper.find('.workflow-graph-inspector-row').exists()).toBe(false)

    await rawJson.trigger('dblclick')
    expect(wrapper.emitted('open-json')?.[0]).toEqual(['运行结果', previewRun, 'succeeded'])
  })
})
