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
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute } from 'vue-router'

import AppBottomPanel from './components/AppBottomPanel.vue'
import AppSidebar from './components/AppSidebar.vue'
import AppTopbar from './components/AppTopbar.vue'
import { useProjectStore } from '@/app/stores/project.store'
import { useSessionStore } from '@/app/stores/session.store'
import { readStorageValue, writeStorageValue } from '@/platform/storage/browser-storage'

const SIDEBAR_COLLAPSED_STORAGE_KEY = 'amvision.web-ui.sidebarCollapsed'
const SIDEBAR_AUTO_COLLAPSE_MEDIA = '(max-width: 899px)'

const projectStore = useProjectStore()
const sessionStore = useSessionStore()
const route = useRoute()
const sidebarCollapsed = ref(readStorageValue(SIDEBAR_COLLAPSED_STORAGE_KEY, 'localStorage') === 'true')
let sidebarAutoCollapseMedia: MediaQueryList | null = null
let removeSidebarAutoCollapseListener: (() => void) | null = null

const isGraphWorkbench = computed(() => route.meta.graphWorkbench === true)

function setSidebarCollapsed(collapsed: boolean): void {
  sidebarCollapsed.value = collapsed
  writeStorageValue(SIDEBAR_COLLAPSED_STORAGE_KEY, String(sidebarCollapsed.value), 'localStorage')
}

function toggleSidebarCollapsed(): void {
  setSidebarCollapsed(!sidebarCollapsed.value)
}

function collapseSidebarWhenViewportIsNarrow(mediaQuery: MediaQueryList): void {
  if (mediaQuery.matches) {
    setSidebarCollapsed(true)
  }
}

onMounted(() => {
  if (sessionStore.isAuthenticated && projectStore.projects.length === 0) {
    void projectStore.loadProjects()
  }

  sidebarAutoCollapseMedia = window.matchMedia(SIDEBAR_AUTO_COLLAPSE_MEDIA)
  collapseSidebarWhenViewportIsNarrow(sidebarAutoCollapseMedia)

  const handleSidebarAutoCollapseChange = (event: MediaQueryListEvent): void => {
    if (event.matches) {
      setSidebarCollapsed(true)
    }
  }

  sidebarAutoCollapseMedia.addEventListener('change', handleSidebarAutoCollapseChange)
  removeSidebarAutoCollapseListener = () => {
    sidebarAutoCollapseMedia?.removeEventListener('change', handleSidebarAutoCollapseChange)
  }
})

onUnmounted(() => {
  removeSidebarAutoCollapseListener?.()
})
</script>
