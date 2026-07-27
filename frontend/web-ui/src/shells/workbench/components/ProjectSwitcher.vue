<template>
  <label class="project-switcher">
    <span>{{ t('common.project') }}</span>
    <SelectField :model-value="projectStore.selectedProjectId" :options="projectOptions" @update:model-value="selectProject" />
  </label>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import { useProjectStore } from '@/app/stores/project.store'
import SelectField from '@/shared/ui/components/Select.vue'

type SelectValue = string | number | boolean | null

const projectStore = useProjectStore()
const { t } = useI18n()

const projectOptions = computed(() => {
  if (projectStore.projects.length === 0) {
    return [{ label: projectStore.selectedProjectId, value: projectStore.selectedProjectId }]
  }
  return projectStore.projects.map((project) => ({
    label: project.project_id === 'project-1' && ['默认项目', 'Default Project', '既定プロジェクト', '기본 프로젝트'].includes(project.display_name ?? '')
      ? t('projects.defaultDisplayName')
      : project.display_name || project.project_id,
    value: project.project_id,
  }))
})

function selectProject(value: SelectValue): void {
  if (typeof value !== 'string') return
  projectStore.selectedProjectId = value
  projectStore.selectProject(value)
}
</script>
