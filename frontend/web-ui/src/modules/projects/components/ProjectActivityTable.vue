<template>
  <ResourceTable embedded class="project-recent-table" :class="{ 'project-active-list': mode === 'running' }" :label="text(mode === 'running' ? 'running' : 'recent')">
    <colgroup><col /><col class="project-activity-status-col" /><col v-if="mode === 'recent'" class="project-activity-date-col" /></colgroup>
    <thead v-if="mode === 'recent'"><tr><th scope="col">{{ text('nameAndType') }}</th><th scope="col">{{ text('status') }}</th><th scope="col">{{ text('updated') }}</th></tr></thead>
    <tbody>
      <tr v-for="item in items" :key="`${item.kind}-${item.resource_id}-${item.runtime_mode || ''}`" :class="{ 'is-clickable': canOpen(item) }" @click="open(item)">
        <td>
          <div class="project-activity-identity">
            <component v-if="mode === 'recent'" :is="icon(item.kind)" :size="22" aria-hidden="true" />
            <div>
              <button v-if="canOpen(item)" type="button" class="resource-table__row-action" data-row-action :title="item.name || item.resource_id" :aria-label="`${text('view')} ${item.name || item.resource_id}`" @click.stop="open(item)">{{ item.name || item.resource_id }}</button>
              <strong v-else :title="item.name || item.resource_id">{{ item.name || item.resource_id }}</strong>
              <small :title="subtitle(item)">{{ subtitle(item) }}</small>
              <template v-if="mode === 'running'">
                <progress v-if="progress(item) !== null" :value="progress(item)!" max="100" :aria-label="item.name || item.resource_id" />
              </template>
            </div>
          </div>
        </td>
        <td><StatusBadge :status="item.state" :title="stateLabel(item.state)" :tone="item.state === 'published' ? 'success' : undefined">{{ stateLabel(item.state) }}</StatusBadge><small v-if="mode === 'running' && progress(item) !== null" class="project-activity-percent">{{ progress(item) }}%</small></td>
        <td v-if="mode === 'recent'" class="project-activity-date" :title="projectDate(item.occurred_at)">{{ projectDate(item.occurred_at) }}</td>
      </tr>
    </tbody>
  </ResourceTable>
</template>
<script setup lang="ts">
import { Box, Database, Workflow, Server, ListChecks } from '@lucide/vue'
import ResourceTable from '@/shared/ui/data-display/ResourceTable.vue'
import StatusBadge from '@/shared/ui/data-display/StatusBadge.vue'
import type { ProjectOverviewItem } from '../services/project.service'
import { projectDate, useProjectText } from '../project-workspace'
const props = withDefaults(defineProps<{ items: ProjectOverviewItem[]; canOpen: (item: ProjectOverviewItem) => boolean; kindLabel: (kind: string) => string; stateLabel: (state: string) => string; mode?: 'recent' | 'running' }>(), { mode: 'recent' })
const emit = defineEmits<{ open: [item: ProjectOverviewItem] }>()
const text = useProjectText()
const icon = (kind: string) => kind.includes('dataset') ? Database : ['runtime', 'application', 'app-version'].includes(kind) ? Workflow : kind === 'deployment' ? Server : kind.includes('model') || /training|conversion|evaluation|inference/.test(kind) ? Box : ListChecks
// 整行和名称入口共用权限判断；原生按钮提供 Tab、Enter、Space 操作。
function open(item: ProjectOverviewItem) { if (props.canOpen(item)) emit('open', item) }
function subtitle(item: ProjectOverviewItem) { return [props.kindLabel(item.kind), ...(props.mode === 'running' ? [item.runtime_mode ? text(item.runtime_mode) : '', item.progress?.stage] : [])].filter(Boolean).join(' · ') }
function progress(item: ProjectOverviewItem) { const value = item.progress?.percent; return typeof value === 'number' && Number.isFinite(value) && value >= 0 && value <= 100 ? Math.round(value) : null }
</script>
