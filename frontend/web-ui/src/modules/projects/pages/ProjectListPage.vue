<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { RefreshCw, Plus } from '@lucide/vue'

import { useProjectStore } from '@/app/stores/project.store'
import { useSessionStore } from '@/app/stores/session.store'
import Button from '@/shared/ui/components/Button.vue'
import EmptyState from '@/shared/ui/feedback/EmptyState.vue'
import InlineError from '@/shared/ui/feedback/InlineError.vue'
import StatusBadge from '@/shared/ui/data-display/StatusBadge.vue'

const projectStore = useProjectStore()
const sessionStore = useSessionStore()

const canBootstrapProject = computed(() =>
  sessionStore.hasScopes(['datasets:write']) || sessionStore.hasScopes(['workflows:write']),
)

onMounted(() => {
  if (projectStore.projects.length === 0) {
    void projectStore.loadProjects()
  }
})

function formatCount(value: unknown): string {
  return typeof value === 'number' ? String(value) : '0'
}
</script>

<template>
  <section class="page-stack">
    <header class="page-header">
      <div>
        <p class="page-kicker">Workspace</p>
        <h1>项目工作台</h1>
      </div>
      <div class="page-actions">
        <Button variant="secondary" @click="projectStore.loadProjects()">
          <RefreshCw :size="16" />
          刷新
        </Button>
        <Button v-if="canBootstrapProject" variant="primary" @click="projectStore.bootstrapDefaultProject()">
          <Plus :size="16" />
          初始化默认项目
        </Button>
      </div>
    </header>

    <InlineError :message="projectStore.error" />

    <EmptyState
      v-if="!projectStore.loading && projectStore.projects.length === 0"
      title="暂无可见 Project"
      description="当前主体没有可见 Project，或本地工作区尚未初始化。"
    >
      <Button v-if="canBootstrapProject" variant="primary" @click="projectStore.bootstrapDefaultProject()">
        <Plus :size="16" />
        初始化默认项目
      </Button>
    </EmptyState>

    <div v-else class="resource-table">
      <table>
        <thead>
          <tr>
            <th>Project</th>
            <th>状态</th>
            <th>数据集</th>
            <th>训练</th>
            <th>部署</th>
            <th>流程</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="project in projectStore.projects"
            :key="project.project_id"
            :class="{ 'is-selected': project.project_id === projectStore.selectedProjectId }"
            @click="projectStore.selectProject(project.project_id)"
          >
            <td>
              <strong>{{ project.display_name || project.project_id }}</strong>
              <span>{{ project.project_id }}</span>
            </td>
            <td>
              <StatusBadge :tone="project.registered_in_catalog === false ? 'warning' : 'success'">
                {{ project.registered_in_catalog === false ? '未登记' : '可用' }}
              </StatusBadge>
            </td>
            <td>{{ formatCount(project.summary?.datasets?.dataset_total) }}</td>
            <td>{{ formatCount(project.summary?.training?.total) }}</td>
            <td>{{ formatCount(project.summary?.deployments?.deployment_instance_total) }}</td>
            <td>{{ formatCount(project.summary?.workflows?.template_total) }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>