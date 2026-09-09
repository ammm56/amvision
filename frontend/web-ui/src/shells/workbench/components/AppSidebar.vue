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
          <img class="brand-mark app-sidebar__collapsed-brand" :src="brandIconUrl" alt="" aria-hidden="true" />
          <PanelLeftOpen class="app-sidebar__collapsed-expand-icon" :size="18" aria-hidden="true" />
        </button>
      </template>
      <template v-else>
        <RouterLink class="app-sidebar__brand" :to="firstAccessiblePath(sessionStore.currentUser)">
          <img class="brand-mark" :src="brandIconUrl" alt="AM" />
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
import { canAccessPath, firstAccessiblePath, settingsPath } from '@/platform/auth/page-access'
import { useSessionStore } from '@/app/stores/session.store'
import UserMenu from './UserMenu.vue'

const route = useRoute()
const { t } = useI18n()
const sessionStore = useSessionStore()
const brandIconUrl = '/favicon.svg'

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
  navigationItems.map((item) => item.path === '/settings' ? { ...item, path: settingsPath(sessionStore.currentUser) ?? '/settings' } : item).filter((item) => canAccessPath(sessionStore.currentUser, item.path)),
)

function isActive(item: NavigationItem): boolean {
  const path = item.path.split('?')[0]
  return route.path === path || route.path.startsWith(`${path}/`)
}
</script>
