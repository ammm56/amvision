<script setup lang="ts">
import { useProjectStore } from '@/app/stores/project.store'

const projectStore = useProjectStore()
</script>

<template>
  <label class="project-switcher">
    <span>Project</span>
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