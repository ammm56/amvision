import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { usePreferencesStore } from '@/app/stores/preferences.store'
import { useProjectStore } from '@/app/stores/project.store'
import { i18n } from '@/platform/i18n'
import { getWorkflowRuntimePreviewSnapshot } from '@/workflows/workflow-editor/services/workflow-runtime-preview.service'
import { listWorkflowAppRuntimes } from '@/workflows/workflow-editor/services/workflow-runtime.service'
import SettingsStartupPagePanel from './SettingsStartupPagePanel.vue'

vi.mock('@/workflows/workflow-editor/services/workflow-runtime-preview.service', () => ({
  getWorkflowRuntimePreviewSnapshot: vi.fn(),
}))
vi.mock('@/workflows/workflow-editor/services/workflow-runtime.service', () => ({
  listWorkflowAppRuntimes: vi.fn(),
}))

const pagination = { offset: 0, limit: 100, totalCount: 1, hasMore: false, nextOffset: null }
const runtime = {
  workflow_runtime_id: 'workflow-runtime-1',
  project_id: 'project-1',
  application_id: 'workflow-app-1',
  display_name: '生产 Runtime',
  observed_state: 'running',
  application_summary: { display_name: '空盘检测' },
}
const snapshot = {
  workflow_runtime_id: 'workflow-runtime-1',
  project_id: 'project-1',
  application_id: 'workflow-app-1',
  app_mode: { format_id: 'amvision.workflow-app-mode.v1', displays: [] },
}

describe('SettingsStartupPagePanel', () => {
  beforeEach(() => {
    localStorage.clear()
    setActivePinia(createPinia())
    usePreferencesStore().initializePreferences()
    useProjectStore().$patch({
      selectedProjectId: 'project-1',
      projects: [{
        project_id: 'project-1',
        display_name: '默认项目',
        description: null,
        metadata: {},
        project_source: 'local_disk',
        storage_prefix: 'projects/project-1',
      }],
    })
    vi.mocked(listWorkflowAppRuntimes).mockResolvedValue({ items: [runtime], pagination } as never)
    vi.mocked(getWorkflowRuntimePreviewSnapshot).mockResolvedValue(snapshot as never)
  })

  it('validates and saves one Runtime App Mode target', async () => {
    const wrapper = mount(SettingsStartupPagePanel, { global: { plugins: [i18n] } })
    await flushPromises()

    await wrapper.findAll('.settings-segmented-control button')[1]!.trigger('click')
    await wrapper.get('.settings-startup-page-runtime-field .ui-select__button').trigger('click')
    await wrapper.get('.settings-startup-page-runtime-field .ui-select__option').trigger('click')
    await flushPromises()
    await wrapper.get('.ui-button--primary').trigger('click')
    await flushPromises()

    expect(usePreferencesStore().startupPage).toEqual({
      mode: 'workflow-runtime-app-mode',
      projectId: 'project-1',
      applicationId: 'workflow-app-1',
      workflowRuntimeId: 'workflow-runtime-1',
    })
    expect(getWorkflowRuntimePreviewSnapshot).toHaveBeenCalledWith('workflow-runtime-1')
    wrapper.unmount()
  })

  it('does not save a Runtime version without App Mode', async () => {
    vi.mocked(getWorkflowRuntimePreviewSnapshot).mockResolvedValue({ ...snapshot, app_mode: null } as never)
    const wrapper = mount(SettingsStartupPagePanel, { global: { plugins: [i18n] } })
    await flushPromises()

    await wrapper.findAll('.settings-segmented-control button')[1]!.trigger('click')
    await wrapper.get('.settings-startup-page-runtime-field .ui-select__button').trigger('click')
    await wrapper.get('.settings-startup-page-runtime-field .ui-select__option').trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('未配置应用模式')
    expect(wrapper.get('.ui-button--primary').attributes('disabled')).toBeDefined()
    expect(usePreferencesStore().startupPage).toEqual({ mode: 'projects' })
    wrapper.unmount()
  })
})
