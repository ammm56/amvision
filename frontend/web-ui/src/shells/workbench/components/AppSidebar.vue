<template>
  <aside class="app-sidebar" :class="{ 'is-collapsed': collapsed }">
    <header class="app-sidebar__header">
      <template v-if="collapsed">
        <button
          class="app-sidebar__collapsed-expand"
          type="button"
          :title="t('navigation.expandSidebarTitle')"
          :aria-label="t('navigation.expandSidebarTitle')"
          @click="emit('toggleCollapsed')"
        >
          <span class="brand-mark app-sidebar__collapsed-brand" aria-hidden="true">AM</span>
          <PanelLeftOpen class="app-sidebar__collapsed-expand-icon" :size="18" aria-hidden="true" />
        </button>
      </template>
      <template v-else>
        <RouterLink class="app-sidebar__brand" to="/projects">
          <span class="brand-mark">AM</span>
          <span class="app-sidebar__brand-name">amvision</span>
        </RouterLink>
        <button
          class="app-sidebar__header-collapse"
          type="button"
          :title="t('navigation.collapseSidebarTitle')"
          :aria-label="t('navigation.collapseSidebarTitle')"
          @click="emit('toggleCollapsed')"
        >
          <PanelLeftClose :size="18" aria-hidden="true" />
        </button>
      </template>
    </header>
    <nav class="app-sidebar__nav">
      <RouterLink
        v-for="item in visibleItems"
        :key="item.path"
        class="app-sidebar__link"
        :class="{ 'is-active': isActive(item) }"
        :to="item.path"
        :title="collapsed ? t(item.labelKey) : undefined"
      >
        <component :is="iconMap[item.icon]" :size="18" />
        <span class="app-sidebar__link-label">{{ t(item.labelKey) }}</span>
      </RouterLink>
    </nav>
    <footer class="app-sidebar__footer">
      <UserMenu :compact="collapsed" />
    </footer>
  </aside>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import {
  Activity,
  Blocks,
  Cable,
  Cpu,
  Database,
  FolderKanban,
  ListChecks,
  PanelLeftClose,
  PanelLeftOpen,
  Rocket,
  Settings,
  Workflow,
} from '@lucide/vue'

import { navigationItems, type NavigationItem } from '@/config/navigation.config'
import { useSessionStore } from '@/app/stores/session.store'
import UserMenu from './UserMenu.vue'

const route = useRoute()
const { t } = useI18n()
const sessionStore = useSessionStore()

defineProps<{
  collapsed: boolean
}>()

const emit = defineEmits<{
  toggleCollapsed: []
}>()

const iconMap = {
  Activity,
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
