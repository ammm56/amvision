<template>
  <aside class="app-sidebar" :class="{ 'is-collapsed': collapsed }">
    <RouterLink class="app-sidebar__brand" to="/projects" :title="collapsed ? 'amvision' : undefined">
      <span class="brand-mark">AM</span>
      <span class="app-sidebar__brand-name">amvision</span>
    </RouterLink>
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
    <button
      class="app-sidebar__link app-sidebar__collapse-toggle"
      type="button"
      :title="collapsed ? t('navigation.expandSidebarTitle') : t('navigation.collapseSidebarTitle')"
      :aria-label="collapsed ? t('navigation.expandSidebarTitle') : t('navigation.collapseSidebarTitle')"
      @click="emit('toggleCollapsed')"
    >
      <PanelLeftOpen v-if="collapsed" :size="18" />
      <PanelLeftClose v-else :size="18" />
      <span class="app-sidebar__collapse-label">{{ collapsed ? t('navigation.expandSidebar') : t('navigation.collapseSidebar') }}</span>
    </button>
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