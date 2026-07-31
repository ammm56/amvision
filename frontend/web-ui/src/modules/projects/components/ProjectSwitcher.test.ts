import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { nextTick } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import ProjectSwitcher from './ProjectSwitcher.vue'
import { useProjectStore } from '@/app/stores/project.store'
import { i18n, setI18nLocale } from '@/platform/i18n'

describe('ProjectSwitcher', () => {
  beforeEach(() => {
    setI18nLocale('zh-CN')
  })

  it('shows project names and changes the selected project', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const projectStore = useProjectStore()
    projectStore.$patch({
      selectedProjectId: 'project-1',
      projects: [
        { project_id: 'project-1', display_name: '默认项目', description: '' },
        { project_id: 'project-2', display_name: '检测项目', description: '' },
      ],
    })
    const selectProject = vi.spyOn(projectStore, 'selectProject').mockResolvedValue()
    const wrapper = mount(ProjectSwitcher, {
      global: { plugins: [pinia, i18n] },
    })

    expect(wrapper.get('.ui-select__value').text()).toBe('默认项目')
    await wrapper.get('.ui-select__button').trigger('click')
    await nextTick()

    const projectOption = wrapper.findAll('.ui-select__option').find((option) => option.text().includes('检测项目'))
    expect(projectOption).toBeDefined()
    await projectOption!.trigger('click')

    expect(projectStore.selectedProjectId).toBe('project-2')
    expect(selectProject).toHaveBeenCalledWith('project-2')
    wrapper.unmount()
  })
})
