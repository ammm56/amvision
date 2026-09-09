<template>
  <main class="workbench-shell" :class="{ 'workbench-shell--sidebar-collapsed': sidebarCollapsed }">
    <AppSidebar :collapsed="sidebarCollapsed" @toggle-collapsed="toggleSidebarCollapsed" />
    <section class="workbench-shell__main">
      <div class="workbench-shell__content" :class="{ 'workbench-shell__content--full-bleed': isFullBleed }">
        <slot />
      </div>
    </section>
  </main>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { canAccessPath } from '@/platform/auth/page-access'

import AppSidebar from './components/AppSidebar.vue'
import { useProjectStore } from '@/app/stores/project.store'
import { useSessionStore } from '@/app/stores/session.store'
import { readStorageValue, writeStorageValue } from '@/platform/storage/browser-storage'

const SIDEBAR_COLLAPSED_STORAGE_KEY = 'amvision.web-ui.sidebarCollapsed'
const SIDEBAR_AUTO_COLLAPSE_MEDIA = '(max-width: 899px)'

const projectStore = useProjectStore()
const sessionStore = useSessionStore()
const route = useRoute()
const router = useRouter()
async function refreshPermissionsOnFocus(): Promise<void> {
  await sessionStore.refreshPermissions()
  if (!sessionStore.isAuthenticated) { await router.replace('/login'); return }
  if (route.path !== '/forbidden' && !canAccessPath(sessionStore.currentUser, route.fullPath)) await router.replace('/forbidden')
}
const sidebarCollapsed = ref(readStorageValue(SIDEBAR_COLLAPSED_STORAGE_KEY, 'localStorage') === 'true')
let sidebarAutoCollapseMedia: MediaQueryList | null = null
let removeSidebarAutoCollapseListener: (() => void) | null = null

const isFullBleed = computed(() => route.meta.graphWorkbench === true || route.meta.fullBleed === true)

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
  window.addEventListener('focus', refreshPermissionsOnFocus)
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
  window.removeEventListener('focus', refreshPermissionsOnFocus)
  removeSidebarAutoCollapseListener?.()
})
</script>
