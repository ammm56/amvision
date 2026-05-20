<template>
  <main class="workbench-shell">
    <AppSidebar />
    <section class="workbench-shell__main" :class="{ 'workbench-shell__main--graph': isGraphWorkbench }">
      <AppTopbar v-if="!isGraphWorkbench" />
      <div class="workbench-shell__content" :class="{ 'workbench-shell__content--full-bleed': isGraphWorkbench }">
        <slot />
      </div>
      <AppBottomPanel v-if="!isGraphWorkbench" />
    </section>
  </main>
</template>

<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'

import AppBottomPanel from './components/AppBottomPanel.vue'
import AppSidebar from './components/AppSidebar.vue'
import AppTopbar from './components/AppTopbar.vue'
import { useProjectStore } from '@/app/stores/project.store'
import { useSessionStore } from '@/app/stores/session.store'

const projectStore = useProjectStore()
const sessionStore = useSessionStore()
const route = useRoute()

const isGraphWorkbench = computed(() => route.meta.graphWorkbench === true)

onMounted(() => {
  if (sessionStore.isAuthenticated && projectStore.projects.length === 0) {
    void projectStore.loadProjects()
  }
})
</script>