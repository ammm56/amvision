<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { HeartPulse, Play, RefreshCw, RotateCcw, Square, Zap } from '@lucide/vue'
import { useI18n } from 'vue-i18n'

import {
  createYoloXDeployment,
  listYoloXDeployments,
  runYoloXDeploymentHealthAction,
  runYoloXDeploymentStatusAction,
  type DeploymentHealthAction,
  type DeploymentRuntimeMode,
  type DeploymentStatusAction,
  type YoloXDeploymentInstance,
  type YoloXDeploymentProcessStatus,
  type YoloXDeploymentRuntimeHealth,
} from '../services/deployment.service'
import { useProjectStore } from '@/app/stores/project.store'
import { useSessionStore } from '@/app/stores/session.store'
import Button from '@/shared/ui/components/Button.vue'
import EmptyState from '@/shared/ui/feedback/EmptyState.vue'
import InlineError from '@/shared/ui/feedback/InlineError.vue'
import StatusBadge from '@/shared/ui/data-display/StatusBadge.vue'

const projectStore = useProjectStore()
const sessionStore = useSessionStore()
const { t } = useI18n()

const deployments = ref<YoloXDeploymentInstance[]>([])
const loading = ref(false)
const creating = ref(false)
const runningAction = ref<string | null>(null)
const errorMessage = ref<string | null>(null)
const lastCreatedDeployment = ref<YoloXDeploymentInstance | null>(null)
const lastRuntimeStatus = ref<YoloXDeploymentProcessStatus | null>(null)
const lastRuntimeHealth = ref<YoloXDeploymentRuntimeHealth | null>(null)

const modelVersionId = ref('')
const modelBuildId = ref('')
const runtimeProfileId = ref('')
const runtimeBackend = ref('')
const runtimePrecision = ref('fp32')
const deviceName = ref('cpu')
const instanceCount = ref(1)
const displayName = ref('')
const runtimeMode = ref<DeploymentRuntimeMode>('sync')

const canWriteModels = computed(() => sessionStore.hasScopes(['models:write']))
const selectedProjectId = computed(() => projectStore.selectedProjectId)

onMounted(async () => {
  if (projectStore.projects.length === 0) {
    await projectStore.loadProjects()
  }
  await refreshPage()
})

function statusTone(status: string | null | undefined): 'neutral' | 'success' | 'warning' | 'danger' | 'info' {
  const normalized = String(status ?? '').toLowerCase()
  if (normalized.includes('running') || normalized.includes('active') || normalized.includes('ready')) return 'success'
  if (normalized.includes('crash') || normalized.includes('error') || normalized.includes('fail')) return 'danger'
  if (normalized.includes('start') || normalized.includes('created') || normalized.includes('stopped')) return 'warning'
  return 'neutral'
}

async function refreshPage(): Promise<void> {
  loading.value = true
  errorMessage.value = null
  try {
    deployments.value = await listYoloXDeployments(selectedProjectId.value)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : t('deploymentOps.messages.loadFailed')
  } finally {
    loading.value = false
  }
}

async function submitDeployment(): Promise<void> {
  if (!modelVersionId.value.trim() && !modelBuildId.value.trim()) {
    errorMessage.value = t('deploymentOps.messages.modelInputRequired')
    return
  }
  creating.value = true
  errorMessage.value = null
  try {
    lastCreatedDeployment.value = await createYoloXDeployment({
      projectId: selectedProjectId.value,
      modelVersionId: modelVersionId.value.trim(),
      modelBuildId: modelBuildId.value.trim(),
      runtimeProfileId: runtimeProfileId.value.trim(),
      runtimeBackend: runtimeBackend.value.trim(),
      runtimePrecision: runtimePrecision.value,
      deviceName: deviceName.value.trim(),
      instanceCount: instanceCount.value,
      displayName: displayName.value,
    })
    await refreshPage()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : t('deploymentOps.messages.createFailed')
  } finally {
    creating.value = false
  }
}

async function runStatusAction(deploymentId: string, action: DeploymentStatusAction): Promise<void> {
  runningAction.value = `${deploymentId}:${runtimeMode.value}:${action}`
  errorMessage.value = null
  try {
    lastRuntimeStatus.value = await runYoloXDeploymentStatusAction(deploymentId, runtimeMode.value, action)
    if (action !== 'status') await refreshPage()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : t('deploymentOps.messages.actionFailed')
  } finally {
    runningAction.value = null
  }
}

async function runHealthAction(deploymentId: string, action: DeploymentHealthAction): Promise<void> {
  runningAction.value = `${deploymentId}:${runtimeMode.value}:${action}`
  errorMessage.value = null
  try {
    lastRuntimeHealth.value = await runYoloXDeploymentHealthAction(deploymentId, runtimeMode.value, action)
    lastRuntimeStatus.value = lastRuntimeHealth.value
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : t('deploymentOps.messages.actionFailed')
  } finally {
    runningAction.value = null
  }
}
</script>

<template>
  <section class="page-stack">
    <header class="page-header">
      <div>
        <p class="page-kicker">{{ t('deploymentOps.kicker') }}</p>
        <h1>{{ t('deploymentOps.title') }}</h1>
        <p class="page-description">{{ t('deploymentOps.description') }}</p>
      </div>
      <div class="page-actions">
        <label class="segmented-field">
          <span>{{ t('deploymentOps.fields.runtimeMode') }}</span>
          <select v-model="runtimeMode">
            <option value="sync">sync</option>
            <option value="async">async</option>
          </select>
        </label>
        <Button variant="secondary" :disabled="loading" @click="refreshPage">
          <RefreshCw :size="16" />
          {{ t('common.refresh') }}
        </Button>
      </div>
    </header>

    <InlineError :message="errorMessage" />

    <form class="form-panel" @submit.prevent="submitDeployment">
      <div>
        <p class="page-kicker">{{ t('deploymentOps.createKicker') }}</p>
        <h2>{{ t('deploymentOps.createTitle') }}</h2>
      </div>
      <div class="form-grid">
        <label class="field">
          <span>{{ t('deploymentOps.fields.projectId') }}</span>
          <input :value="selectedProjectId" disabled />
        </label>
        <label class="field">
          <span>{{ t('deploymentOps.fields.modelVersionId') }}</span>
          <input v-model="modelVersionId" />
        </label>
        <label class="field">
          <span>{{ t('deploymentOps.fields.modelBuildId') }}</span>
          <input v-model="modelBuildId" />
        </label>
        <label class="field">
          <span>{{ t('deploymentOps.fields.runtimeProfileId') }}</span>
          <input v-model="runtimeProfileId" />
        </label>
        <label class="field">
          <span>{{ t('deploymentOps.fields.runtimeBackend') }}</span>
          <select v-model="runtimeBackend">
            <option value="">{{ t('common.none') }}</option>
            <option value="pytorch">pytorch</option>
            <option value="onnxruntime">onnxruntime</option>
            <option value="openvino">openvino</option>
            <option value="tensorrt">tensorrt</option>
          </select>
        </label>
        <label class="field">
          <span>{{ t('deploymentOps.fields.runtimePrecision') }}</span>
          <select v-model="runtimePrecision">
            <option value="fp32">fp32</option>
            <option value="fp16">fp16</option>
          </select>
        </label>
        <label class="field">
          <span>{{ t('deploymentOps.fields.deviceName') }}</span>
          <input v-model="deviceName" />
        </label>
        <label class="field">
          <span>{{ t('deploymentOps.fields.instanceCount') }}</span>
          <input v-model.number="instanceCount" type="number" min="1" />
        </label>
        <label class="field field--wide">
          <span>{{ t('deploymentOps.fields.displayName') }}</span>
          <input v-model="displayName" />
        </label>
      </div>
      <div class="form-actions">
        <Button variant="primary" type="submit" :disabled="!canWriteModels || creating">
          <Zap :size="16" />
          {{ creating ? t('deploymentOps.actions.creating') : t('deploymentOps.actions.create') }}
        </Button>
      </div>
      <p v-if="lastCreatedDeployment" class="result-note">
        {{ t('deploymentOps.messages.created') }} {{ lastCreatedDeployment.deployment_instance_id }}
      </p>
    </form>

    <section v-if="lastRuntimeStatus" class="resource-section">
      <div>
        <p class="page-kicker">{{ t('deploymentOps.runtimeKicker') }}</p>
        <h2>{{ t('deploymentOps.runtimeTitle') }}</h2>
      </div>
      <div class="summary-grid">
        <div>
          <span>{{ t('deploymentOps.fields.deploymentId') }}</span>
          <strong>{{ lastRuntimeStatus.deployment_instance_id }}</strong>
        </div>
        <div>
          <span>{{ t('deploymentOps.fields.runtimeMode') }}</span>
          <strong>{{ lastRuntimeStatus.runtime_mode }}</strong>
        </div>
        <div>
          <span>{{ t('deploymentOps.fields.processState') }}</span>
          <strong>{{ lastRuntimeStatus.process_state }}</strong>
        </div>
        <div>
          <span>{{ t('deploymentOps.fields.processId') }}</span>
          <strong>{{ lastRuntimeStatus.process_id ?? '-' }}</strong>
        </div>
      </div>
      <div v-if="lastRuntimeHealth" class="summary-grid">
        <div>
          <span>{{ t('deploymentOps.fields.healthyInstances') }}</span>
          <strong>{{ lastRuntimeHealth.healthy_instance_count }}</strong>
        </div>
        <div>
          <span>{{ t('deploymentOps.fields.warmedInstances') }}</span>
          <strong>{{ lastRuntimeHealth.warmed_instance_count }}</strong>
        </div>
        <div>
          <span>{{ t('deploymentOps.fields.pinnedBytes') }}</span>
          <strong>{{ lastRuntimeHealth.pinned_output_total_bytes }}</strong>
        </div>
        <div>
          <span>{{ t('deploymentOps.fields.lastError') }}</span>
          <strong>{{ lastRuntimeHealth.last_error || '-' }}</strong>
        </div>
      </div>
    </section>

    <section class="resource-section">
      <div>
        <p class="page-kicker">{{ t('deploymentOps.listKicker') }}</p>
        <h2>{{ t('deploymentOps.listTitle') }}</h2>
      </div>
      <EmptyState v-if="!loading && deployments.length === 0" :title="t('deploymentOps.emptyTitle')" :description="t('deploymentOps.emptyDescription')" />
      <div v-else class="resource-table">
        <table>
          <thead>
            <tr>
              <th>{{ t('deploymentOps.columns.deployment') }}</th>
              <th>{{ t('deploymentOps.columns.status') }}</th>
              <th>{{ t('deploymentOps.columns.model') }}</th>
              <th>{{ t('deploymentOps.columns.runtime') }}</th>
              <th>{{ t('deploymentOps.columns.instances') }}</th>
              <th>{{ t('deploymentOps.columns.actions') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in deployments" :key="item.deployment_instance_id">
              <td>
                <strong>{{ item.display_name || item.deployment_instance_id }}</strong>
                <span>{{ item.deployment_instance_id }}</span>
              </td>
              <td><StatusBadge :tone="statusTone(item.status)">{{ item.status }}</StatusBadge></td>
              <td>
                <strong>{{ item.model_name }}</strong>
                <span>{{ item.model_version_id }}{{ item.model_build_id ? ` / ${item.model_build_id}` : '' }}</span>
              </td>
              <td>{{ item.runtime_execution_mode }}</td>
              <td>{{ item.instance_count }}</td>
              <td>
                <div class="table-actions table-actions--wrap">
                  <Button size="sm" variant="secondary" :disabled="!canWriteModels || runningAction !== null" @click="runStatusAction(item.deployment_instance_id, 'start')">
                    <Play :size="14" />{{ t('deploymentOps.actions.start') }}
                  </Button>
                  <Button size="sm" variant="ghost" :disabled="runningAction !== null" @click="runStatusAction(item.deployment_instance_id, 'status')">
                    <HeartPulse :size="14" />{{ t('deploymentOps.actions.status') }}
                  </Button>
                  <Button size="sm" variant="ghost" :disabled="!canWriteModels || runningAction !== null" @click="runHealthAction(item.deployment_instance_id, 'warmup')">
                    <Zap :size="14" />{{ t('deploymentOps.actions.warmup') }}
                  </Button>
                  <Button size="sm" variant="ghost" :disabled="runningAction !== null" @click="runHealthAction(item.deployment_instance_id, 'health')">
                    <HeartPulse :size="14" />{{ t('deploymentOps.actions.health') }}
                  </Button>
                  <Button size="sm" variant="ghost" :disabled="!canWriteModels || runningAction !== null" @click="runHealthAction(item.deployment_instance_id, 'reset')">
                    <RotateCcw :size="14" />{{ t('deploymentOps.actions.reset') }}
                  </Button>
                  <Button size="sm" variant="danger" :disabled="!canWriteModels || runningAction !== null" @click="runStatusAction(item.deployment_instance_id, 'stop')">
                    <Square :size="14" />{{ t('deploymentOps.actions.stop') }}
                  </Button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  </section>
</template>