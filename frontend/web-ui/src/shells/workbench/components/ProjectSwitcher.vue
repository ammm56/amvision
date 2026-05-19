<template>
  <label class="project-switcher">
    <span>{{ t('common.project') }}</span>
    <select v-model="projectStore.selectedProjectId" @change="projectStore.selectProject(projectStore.selectedProjectId)">
      <option v-for="project in projectStore.projects" :key="project.project_id" :value="project.project_id">
        {{ project.display_name || project.project_id }}
      </option>
      <option v-if="projectStore.projects.length === 0" :value="projectStore.selectedProjectId">
        {{ projectStore.selectedProjectId }}
      </option>
    </select>
  </label>
</template>

<script setup lang="ts">
import { useI18n } from 'vue-i18n'

import { useProjectStore } from '@/app/stores/project.store'

const projectStore = useProjectStore()
const { t } = useI18n()
</script>