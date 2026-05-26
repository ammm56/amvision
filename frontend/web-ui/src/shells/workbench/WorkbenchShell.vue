<template>
  <main class="workbench-shell" :class="{ 'workbench-shell--sidebar-collapsed': sidebarCollapsed }">
    <AppSidebar :collapsed="sidebarCollapsed" @toggle-collapsed="toggleSidebarCollapsed" />
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
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'

import AppBottomPanel from './components/AppBottomPanel.vue'
import AppSidebar from './components/AppSidebar.vue'
import AppTopbar from './components/AppTopbar.vue'
import { useProjectStore } from '@/app/stores/project.store'
import { useSessionStore } from '@/app/stores/session.store'
import { readStorageValue, writeStorageValue } from '@/platform/storage/browser-storage'

const SIDEBAR_COLLAPSED_STORAGE_KEY = 'amvision.web-ui.sidebarCollapsed'

const projectStore = useProjectStore()
const sessionStore = useSessionStore()
const route = useRoute()
const sidebarCollapsed = ref(readStorageValue(SIDEBAR_COLLAPSED_STORAGE_KEY, 'localStorage') === 'true')

const isGraphWorkbench = computed(() => route.meta.graphWorkbench === true)

function toggleSidebarCollapsed(): void {
  sidebarCollapsed.value = !sidebarCollapsed.value
  writeStorageValue(SIDEBAR_COLLAPSED_STORAGE_KEY, String(sidebarCollapsed.value), 'localStorage')
}

onMounted(() => {
  if (sessionStore.isAuthenticated && projectStore.projects.length === 0) {
    void projectStore.loadProjects()
  }
})
</script>