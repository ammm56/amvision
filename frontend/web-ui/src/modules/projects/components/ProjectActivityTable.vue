<template>
  <table class="project-recent-table">
    <thead><tr><th>{{ text('nameAndType') }}</th><th>{{ text('status') }}</th><th>{{ text('updated') }}</th><th>{{ text('actions') }}</th></tr></thead>
    <tbody><tr v-for="item in items" :key="`${item.kind}-${item.resource_id}`">
      <td><div class="project-activity-identity"><component :is="icon(item.kind)" :size="22" aria-hidden="true" /><div><strong>{{ item.name || item.resource_id }}</strong><small>{{ kindLabel(item.kind) }}</small></div></div></td>
      <td><span class="state" :class="stateClass(item.state)">{{ stateLabel(item.state) }}</span></td>
      <td class="project-activity-date">{{ projectDate(item.occurred_at) }}</td>
      <td><button v-if="canOpen(item)" class="project-link" :aria-label="`${text('view')} ${item.name || item.resource_id}`" @click="emit('open', item)"><ChevronRight :size="16" /></button><span v-else>—</span></td>
    </tr></tbody>
  </table>
</template>
<script setup lang="ts">
import { Box, Database, Workflow, Server, ListChecks, ChevronRight } from '@lucide/vue'
import type { ProjectOverviewItem } from '../services/project.service'
import { projectDate, useProjectText } from '../project-workspace'
defineProps<{ items: ProjectOverviewItem[]; canOpen: (item: ProjectOverviewItem) => boolean; kindLabel: (kind: string) => string; stateLabel: (state: string) => string }>()
const emit = defineEmits<{ open: [item: ProjectOverviewItem] }>()
const text = useProjectText()
const icon = (kind: string) => kind.includes('dataset') ? Database : ['runtime', 'application', 'app-version'].includes(kind) ? Workflow : kind === 'deployment' ? Server : kind.includes('model') || /training|conversion|evaluation|inference/.test(kind) ? Box : ListChecks
const stateClass = (state: string) => ({ 'is-ok': ['running', 'ready', 'succeeded', 'completed', 'published'].includes(state), 'is-failed': ['failed', 'error'].includes(state) })
</script>
