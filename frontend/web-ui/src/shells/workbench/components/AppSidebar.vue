<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import {
  Blocks,
  Cable,
  Cpu,
  Database,
  FolderKanban,
  ListChecks,
  Rocket,
  Settings,
  Workflow,
} from '@lucide/vue'

import { navigationItems, type NavigationItem } from '@/config/navigation.config'
import { useSessionStore } from '@/app/stores/session.store'

const route = useRoute()
const sessionStore = useSessionStore()

const iconMap = {
  FolderKanban,
  ListChecks,
  Database,
  Cpu,
  Rocket,
  Workflow,
  Cable,
  Blocks,
  Settings,
}

const visibleItems = computed(() =>
  navigationItems.filter((item) => item.requiredScopes.length === 0 || sessionStore.hasScopes(item.requiredScopes)),
)

function isActive(item: NavigationItem): boolean {
  return route.path === item.path || route.path.startsWith(`${item.path}/`)
}
</script>

<template>
  <aside class="app-sidebar">
    <RouterLink class="app-sidebar__brand" to="/projects">
      <span class="brand-mark">AM</span>
      <span>amvision</span>
    </RouterLink>
    <nav>
      <RouterLink
        v-for="item in visibleItems"
        :key="item.path"
        class="app-sidebar__link"
        :class="{ 'is-active': isActive(item) }"
        :to="item.path"
      >
        <component :is="iconMap[item.icon]" :size="18" />
        <span>{{ item.label }}</span>
      </RouterLink>
    </nav>
  </aside>
</template>