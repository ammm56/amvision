<template>
  <main class="workbench-shell">
    <AppSidebar />
    <section class="workbench-shell__main">
      <AppTopbar />
      <div class="workbench-shell__content">
        <slot />
      </div>
      <AppBottomPanel />
    </section>
  </main>
</template>

<script setup lang="ts">
import { onMounted } from 'vue'

import AppBottomPanel from './components/AppBottomPanel.vue'
import AppSidebar from './components/AppSidebar.vue'
import AppTopbar from './components/AppTopbar.vue'
import { useProjectStore } from '@/app/stores/project.store'
import { useSessionStore } from '@/app/stores/session.store'

const projectStore = useProjectStore()
const sessionStore = useSessionStore()

onMounted(() => {
  if (sessionStore.isAuthenticated && projectStore.projects.length === 0) {
    void projectStore.loadProjects()
  }
})
</script>