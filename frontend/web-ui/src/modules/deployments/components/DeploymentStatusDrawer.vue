<template>
  <SideDrawer
    :open="open"
    :title="t('deploymentOps.statusDetailsTitle')"
    :close-label="t('common.close')"
    @close="emit('close')"
  >
    <template v-if="deployment">
      <div class="deployment-status-drawer__identity">
        <strong>{{ displayName }}</strong>
        <StatusBadge :tone="summaryTone" with-dot>{{ summaryLabel }}</StatusBadge>
      </div>

      <section class="deployment-status-drawer__section">
        <h3>{{ t('deploymentOps.instanceDetailsTitle') }}</h3>
        <dl class="deployment-status-drawer__grid">
          <div>
            <dt>{{ t('deploymentOps.fields.deploymentId') }}</dt>
            <dd>{{ deployment.deployment_instance_id }}</dd>
          </div>
          <div>
            <dt>{{ t('deploymentOps.columns.status') }}</dt>
            <dd>{{ deployment.status || '-' }}</dd>
          </div>
          <div>
            <dt>{{ t('deploymentOps.columns.model') }}</dt>
            <dd>{{ deployment.model_name }}</dd>
          </div>
          <div>
            <dt>{{ t('deploymentOps.fields.modelVersionId') }}</dt>
            <dd>{{ deployment.model_version_id || '-' }}</dd>
          </div>
          <div>
            <dt>{{ t('deploymentOps.fields.modelBuildId') }}</dt>
            <dd>{{ deployment.model_build_id || '-' }}</dd>
          </div>
          <div>
            <dt>{{ t('deploymentOps.source.kind') }}</dt>
            <dd>{{ deployment.source_kind || '-' }}</dd>
          </div>
          <div>
            <dt>{{ t('deploymentOps.columns.runtime') }}</dt>
            <dd>{{ runtimeLabel }}</dd>
          </div>
          <div>
            <dt>{{ t('deploymentOps.fields.runtimeProfileId') }}</dt>
            <dd>{{ deployment.runtime_profile_id || '-' }}</dd>
          </div>
          <div>
            <dt>{{ t('deploymentOps.fields.instanceCount') }}</dt>
            <dd>{{ deployment.runtime_configuration.execution.instance_count }}</dd>
          </div>
          <div>
            <dt>{{ t('deploymentOps.fields.inputSize') }}</dt>
            <dd>{{ inputSizeLabel }}</dd>
          </div>
          <div>
            <dt>{{ t('deploymentOps.runtimeConfig.keepWarm') }}</dt>
            <dd>{{ keepWarmLabel }}</dd>
          </div>
        </dl>
      </section>

      <section class="deployment-status-drawer__section">
        <h3>{{ t('deploymentOps.runtimeTitle') }}</h3>
        <dl class="deployment-status-drawer__grid">
          <div>
            <dt>{{ t('deploymentOps.fields.runtimeMode') }}</dt>
            <dd>{{ status?.runtime_mode || deployment.runtime_execution_mode }}</dd>
          </div>
          <div>
            <dt>{{ t('deploymentOps.fields.processState') }}</dt>
            <dd>{{ status?.process_state || t('deploymentOps.states.notInspected') }}</dd>
          </div>
          <div>
            <dt>{{ t('deploymentOps.fields.desiredState') }}</dt>
            <dd>{{ status?.desired_state || '-' }}</dd>
          </div>
          <div>
            <dt>{{ t('deploymentOps.fields.observedState') }}</dt>
            <dd>{{ status?.observed_state || '-' }}</dd>
          </div>
          <div>
            <dt>{{ t('deploymentOps.fields.generation') }}</dt>
            <dd>{{ status?.generation ?? '-' }}</dd>
          </div>
          <div>
            <dt>{{ t('deploymentOps.fields.processId') }}</dt>
            <dd>{{ status?.process_id ?? '-' }}</dd>
          </div>
          <div>
            <dt>{{ t('deploymentOps.fields.healthyInstances') }}</dt>
            <dd>{{ health?.healthy_instance_count ?? '-' }}</dd>
          </div>
          <div>
            <dt>{{ t('deploymentOps.fields.warmedInstances') }}</dt>
            <dd>{{ health?.warmed_instance_count ?? '-' }}</dd>
          </div>
          <div v-if="cpuResourceSummary">
            <dt>{{ t('deploymentOps.fields.cpuDeploymentThreadCapacity') }}</dt>
            <dd>{{ cpuResourceSummary.deploymentThreadCapacity }} / {{ cpuResourceSummary.physicalCoreCount }}</dd>
          </div>
          <div v-if="cpuResourceSummary">
            <dt>{{ t('deploymentOps.fields.cpuThreadsPerInstance') }}</dt>
            <dd>{{ cpuResourceSummary.threadsPerInstance }}</dd>
          </div>
          <div v-if="cpuResourceSummary">
            <dt>{{ t('deploymentOps.fields.cpuSchedulingPolicy') }}</dt>
            <dd>{{ t('deploymentOps.fields.cpuSchedulingPolicyShared') }}</dd>
          </div>
          <div>
            <dt>{{ t('deploymentOps.fields.pinnedBytes') }}</dt>
            <dd>{{ health?.pinned_output_total_bytes ?? '-' }}</dd>
          </div>
          <div class="deployment-status-drawer__grid-item--wide">
            <dt>{{ t('deploymentOps.fields.lastError') }}</dt>
            <dd>{{ health?.last_error || status?.last_error || '-' }}</dd>
          </div>
        </dl>

        <div v-if="health?.configuration_warnings.length" class="runtime-configuration-warnings">
          <strong>{{ t('deploymentOps.runtimeDiagnostics.warnings') }}</strong>
          <ul>
            <li v-for="warning in health.configuration_warnings" :key="warning">{{ warning }}</li>
          </ul>
        </div>
        <div v-if="health" class="runtime-configuration-diagnostics">
          <details>
            <summary>{{ t('deploymentOps.runtimeDiagnostics.requested') }}</summary>
            <pre>{{ formatRuntimeConfiguration(health.requested_runtime_configuration) }}</pre>
          </details>
          <details>
            <summary>{{ t('deploymentOps.runtimeDiagnostics.effective') }}</summary>
            <pre>{{ formatRuntimeConfiguration(health.effective_runtime_configuration) }}</pre>
          </details>
        </div>
      </section>

      <section class="deployment-status-drawer__section">
        <h3>{{ t('deploymentOps.eventsTitle') }}</h3>
        <InlineMessage v-if="eventsLoading" :message="t('deploymentOps.messages.eventsLoading')" />
        <EmptyState
          v-else-if="sortedEvents.length === 0"
          :title="t('deploymentOps.emptyEventsTitle')"
          :description="t('deploymentOps.emptyEventsDescription')"
        />
        <ol v-else class="deployment-event-timeline">
          <li v-for="event in sortedEvents" :key="`${event.runtime_mode}-${event.sequence}`">
            <span class="deployment-event-timeline__marker" aria-hidden="true" />
            <div class="deployment-event-timeline__content">
              <div>
                <strong>{{ event.event_type }}</strong>
                <time>{{ formatSystemDateTime(event.created_at) }}</time>
              </div>
              <p>{{ event.message }}</p>
            </div>
          </li>
        </ol>
      </section>
    </template>
  </SideDrawer>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import { formatSystemDateTime } from '@/shared/formatters/date-time'
import SideDrawer from '@/shared/ui/components/SideDrawer.vue'
import StatusBadge from '@/shared/ui/data-display/StatusBadge.vue'
import EmptyState from '@/shared/ui/feedback/EmptyState.vue'
import InlineMessage from '@/shared/ui/feedback/InlineMessage.vue'
import type {
  TaskDeploymentInstance,
  TaskDeploymentProcessEvent,
  TaskDeploymentProcessStatus,
  TaskDeploymentRuntimeHealth,
} from '../services/deployment.service'

interface CpuResourceSummary {
  physicalCoreCount: number
  deploymentThreadCapacity: number
  threadsPerInstance: number
}

type StatusBadgeTone = 'neutral' | 'success' | 'warning' | 'danger' | 'info'

const props = defineProps<{
  open: boolean
  deployment: TaskDeploymentInstance | null
  status: TaskDeploymentProcessStatus | null
  health: TaskDeploymentRuntimeHealth | null
  cpuResourceSummary: CpuResourceSummary | null
  events: TaskDeploymentProcessEvent[]
  eventsLoading: boolean
  displayName: string
  summaryLabel: string
  summaryTone: StatusBadgeTone
}>()

const emit = defineEmits<{ close: [] }>()
const { t } = useI18n()

const sortedEvents = computed(() => [...props.events].sort(compareEventsNewestFirst))
const runtimeLabel = computed(() => {
  if (!props.deployment) return '-'
  const backend = props.deployment.runtime_backend || 'pytorch'
  const precision = props.deployment.runtime_precision || 'fp32'
  const device = props.deployment.device_name ? ` / ${props.deployment.device_name}` : ''
  return `${backend} ${precision}${device}`
})
const inputSizeLabel = computed(() => {
  const inputSize = props.deployment?.input_size
  return inputSize ? `${inputSize.width} x ${inputSize.height}` : '-'
})
const keepWarmLabel = computed(() => {
  const lifecycle = props.deployment?.runtime_configuration.lifecycle
  if (lifecycle?.keep_warm_enabled !== true) return t('deploymentOps.options.disabled')
  const interval = typeof lifecycle.keep_warm_interval_seconds === 'number'
    && Number.isFinite(lifecycle.keep_warm_interval_seconds)
    && lifecycle.keep_warm_interval_seconds >= 0.01
    ? lifecycle.keep_warm_interval_seconds
    : 0.1
  return `${t('deploymentOps.options.enabled')} · ${interval} s`
})

function compareEventsNewestFirst(left: TaskDeploymentProcessEvent, right: TaskDeploymentProcessEvent): number {
  const leftTimestamp = Date.parse(left.created_at)
  const rightTimestamp = Date.parse(right.created_at)
  if (Number.isFinite(leftTimestamp) && Number.isFinite(rightTimestamp) && leftTimestamp !== rightTimestamp) {
    return rightTimestamp - leftTimestamp
  }
  return right.sequence - left.sequence
}

function formatRuntimeConfiguration(value: Record<string, unknown>): string {
  return JSON.stringify(value, null, 2)
}
</script>

<style scoped>
.deployment-status-drawer__identity {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--am-space-md);
  min-width: 0;
  padding-bottom: var(--am-space-lg);
  border-bottom: 1px solid var(--am-border);
}

.deployment-status-drawer__identity strong {
  min-width: 0;
  color: var(--am-text-strong);
  overflow-wrap: anywhere;
}

.deployment-status-drawer__section {
  margin-top: var(--am-space-xl);
}

.deployment-status-drawer__section h3 {
  margin: 0 0 var(--am-space-md);
  color: var(--am-text-strong);
  font-size: 15px;
}

.deployment-status-drawer__grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--am-space-sm);
  margin: 0;
}

.deployment-status-drawer__grid > div {
  min-width: 0;
  padding: var(--am-space-md);
  border: 1px solid var(--am-border);
  border-radius: var(--am-radius-md);
  background: var(--am-surface-soft);
}

.deployment-status-drawer__grid-item--wide {
  grid-column: 1 / -1;
}

.deployment-status-drawer__grid dt {
  margin-bottom: var(--am-space-xs);
  color: var(--am-text-muted);
  font-size: 12px;
  font-weight: 700;
}

.deployment-status-drawer__grid dd {
  margin: 0;
  color: var(--am-text-strong);
  overflow-wrap: anywhere;
}

.runtime-configuration-warnings {
  display: grid;
  gap: 8px;
  margin-top: 12px;
  padding: 12px;
  border: 1px solid var(--am-warning-border);
  border-radius: 8px;
  background: var(--am-warning-surface);
}

.runtime-configuration-warnings ul {
  margin: 0;
  padding-left: 20px;
}

.runtime-configuration-diagnostics {
  display: grid;
  gap: 8px;
  margin-top: 12px;
}

.runtime-configuration-diagnostics details {
  border: 1px solid var(--am-border);
  border-radius: 8px;
  background: var(--am-surface);
}

.runtime-configuration-diagnostics summary {
  padding: 10px 12px;
  cursor: pointer;
  font-weight: 600;
}

.runtime-configuration-diagnostics pre {
  max-height: 320px;
  margin: 0;
  padding: 12px;
  overflow: auto;
  border-top: 1px solid var(--am-border);
  font-size: 12px;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.deployment-event-timeline {
  display: grid;
  gap: 0;
  margin: 0;
  padding: 0;
  list-style: none;
}

.deployment-event-timeline li {
  position: relative;
  display: grid;
  grid-template-columns: 18px minmax(0, 1fr);
  gap: var(--am-space-sm);
  padding-bottom: var(--am-space-lg);
}

.deployment-event-timeline li:not(:last-child)::before {
  position: absolute;
  top: 12px;
  bottom: 0;
  left: 5px;
  width: 1px;
  content: '';
  background: var(--am-border);
}

.deployment-event-timeline__marker {
  position: relative;
  z-index: 1;
  width: 11px;
  height: 11px;
  margin-top: 4px;
  border: 2px solid var(--am-info-text);
  border-radius: 50%;
  background: var(--am-surface);
}

.deployment-event-timeline__content,
.deployment-event-timeline__content div {
  min-width: 0;
}

.deployment-event-timeline__content div {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--am-space-md);
}

.deployment-event-timeline__content strong,
.deployment-event-timeline__content time,
.deployment-event-timeline__content p {
  overflow-wrap: anywhere;
}

.deployment-event-timeline__content time,
.deployment-event-timeline__content p {
  color: var(--am-text-muted);
  font-size: 12px;
}

.deployment-event-timeline__content p {
  margin: 3px 0 0;
  line-height: 1.5;
}

@media (max-width: 620px) {
  .deployment-status-drawer__grid {
    grid-template-columns: 1fr;
  }

  .deployment-status-drawer__grid-item--wide {
    grid-column: auto;
  }

  .deployment-event-timeline__content div {
    display: grid;
    gap: 2px;
  }
}
</style>
