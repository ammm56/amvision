<template>
  <SideDrawer
    :open="open"
    :title="t('deploymentWorkspace.capabilities.title')"
    :close-label="t('common.close')"
    panel-class="deployment-capabilities-drawer"
    @close="emit('close')"
  >
    <div class="capabilities-meta-bar">
      <span>{{ t('deploymentWorkspace.capabilities.updatedAt') }}：{{ updatedAtLabel }}</span>
      <Button size="sm" variant="secondary" :loading="loading" @click="refreshAll">
        <RefreshCw :size="14" />
        {{ t('common.refresh') }}
      </Button>
    </div>

    <section class="capabilities-section">
      <h3>{{ t('deploymentWorkspace.capabilities.currentHost') }}</h3>
      <dl v-if="hostSummaryRows.length" class="capabilities-host-card">
        <div v-for="row in hostSummaryRows" :key="row.label">
          <dt>{{ row.label }}</dt>
          <dd>{{ row.value }}</dd>
        </div>
      </dl>
      <p v-else class="capabilities-empty-note">{{ t('deploymentWorkspace.capabilities.description') }}</p>
    </section>

    <section class="capabilities-section">
      <h3>{{ t('deploymentWorkspace.capabilities.hostDevices') }}</h3>
      <div v-if="capabilityTableRows.length" class="capabilities-table-wrap">
        <TooltipProvider :delay-duration="120">
          <table>
            <colgroup>
              <col style="width: 18%" />
              <col style="width: 26%" />
              <col style="width: 18%" />
              <col style="width: 38%" />
            </colgroup>
            <thead>
              <tr>
                <th :title="t('deploymentWorkspace.capabilities.backendCol')">{{ t('deploymentWorkspace.capabilities.backendCol') }}</th>
                <th :title="t('deploymentWorkspace.capabilities.deviceCol')">{{ t('deploymentWorkspace.capabilities.deviceCol') }}</th>
                <th :title="t('deploymentWorkspace.capabilities.availabilityCol')">{{ t('deploymentWorkspace.capabilities.availabilityCol') }}</th>
                <th :title="t('deploymentWorkspace.capabilities.reasonCol')">{{ t('deploymentWorkspace.capabilities.reasonCol') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in capabilityTableRows" :key="`${row.backendKey}-${row.device}`">
                <td class="capabilities-backend-td">
                  <TooltipRoot>
                    <TooltipTrigger as-child>
                      <span class="capabilities-backend-cell" tabindex="0">
                        <DeploymentRuntimeBadge
                          :backend="row.backendKey"
                          backend-only
                          :muted="!row.available"
                          :tooltip="row.backend"
                        />
                      </span>
                    </TooltipTrigger>
                    <TooltipPortal>
                      <TooltipContent
                        class="capabilities-backend-tooltip"
                        side="top"
                        :side-offset="6"
                        :collision-padding="12"
                      >
                        {{ row.backend }}
                      </TooltipContent>
                    </TooltipPortal>
                  </TooltipRoot>
                </td>
                <td :title="row.device">{{ row.device }}</td>
                <td :title="row.available ? t('deploymentWorkspace.capabilities.available') : t('deploymentWorkspace.capabilities.unavailable')">
                  <span class="capability-status" :class="{ 'is-available': row.available }">
                    <span class="capability-status__dot" aria-hidden="true" />
                    <span>{{ row.available ? t('deploymentWorkspace.capabilities.available') : t('deploymentWorkspace.capabilities.unavailable') }}</span>
                  </span>
                </td>
                <td :title="row.reason">{{ row.reason }}</td>
              </tr>
            </tbody>
          </table>
        </TooltipProvider>
      </div>
      <EmptyState v-else :title="t('deploymentWorkspace.capabilities.unavailable')" />
    </section>

    <details class="capabilities-probe">
      <summary>{{ t('deploymentWorkspace.capabilities.querySection') }}</summary>
      <div class="capabilities-probe__body">
        <div class="capabilities-query">
          <div class="field">
            <span>{{ t('deploymentWorkspace.capabilities.backend') }}</span>
            <SelectField floating :aria-label="t('deploymentWorkspace.capabilities.backend')" :model-value="backend" :options="backendOptions" @update:model-value="setBackend" />
          </div>
          <div class="field">
            <span>{{ t('deploymentWorkspace.capabilities.device') }}</span>
            <SelectField floating :aria-label="t('deploymentWorkspace.capabilities.device')" :model-value="device" :options="deviceOptions" @update:model-value="setDevice" />
          </div>
          <Button size="sm" variant="secondary" :loading="loading" @click="inspect">
            {{ t('deploymentWorkspace.capabilities.queryAction') }}
          </Button>
        </div>

        <InlineError :message="error" />
        <LoadingPanel v-if="loading && !capabilities" compact :title="t('deploymentOps.messages.capabilitiesLoading')" />
        <div v-else-if="capabilities" class="capabilities-result">
          <div class="capabilities-result__status">
            <StatusBadge :tone="capabilities.available ? 'success' : 'warning'">
              {{ capabilities.available ? t('deploymentWorkspace.capabilities.available') : t('deploymentWorkspace.capabilities.unavailable') }}
            </StatusBadge>
            <DeploymentRuntimeBadge
              :backend="capabilities.runtime_backend"
              :device="capabilities.device_name"
              :tooltip="resultBadgeTooltip"
            />
            <span class="capabilities-device-pill">{{ resultDeviceLabel }}</span>
          </div>

          <div v-if="capabilities.supported_backend_fields.length" class="capabilities-group">
            <h4>{{ t('deploymentWorkspace.capabilities.supportedFields') }}</h4>
            <ul class="capabilities-chips">
              <li v-for="field in capabilities.supported_backend_fields" :key="field" :title="field">{{ formatFieldLabel(field) }}</li>
            </ul>
          </div>

          <div v-if="readOnlyEntries.length" class="capabilities-group">
            <h4>{{ t('deploymentWorkspace.capabilities.readOnlyProperties') }}</h4>
            <div class="capabilities-prop-table-wrap">
              <table class="capabilities-prop-table">
                <colgroup>
                  <col style="width: 36%" />
                  <col style="width: 64%" />
                </colgroup>
                <thead>
                  <tr>
                    <th>{{ t('deploymentWorkspace.capabilities.propertyCol') }}</th>
                    <th>{{ t('deploymentWorkspace.capabilities.valueCol') }}</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="entry in readOnlyEntries" :key="entry.rawKey">
                    <td class="capabilities-prop-key" :title="entry.rawKey">
                      <span>{{ entry.label }}</span>
                    </td>
                    <td class="capabilities-prop-val">
                      <span
                        v-if="entry.kind === 'boolean'"
                        class="capabilities-bool-badge"
                        :class="entry.boolValue ? 'is-true' : 'is-false'"
                      >
                        {{ entry.boolValue ? t('deploymentWorkspace.capabilities.supported') : t('deploymentWorkspace.capabilities.unsupported') }}
                      </span>
                      <span v-else-if="entry.kind === 'range'" class="capabilities-range-value">
                        {{ entry.textValue }}
                      </span>
                      <div v-else-if="entry.kind === 'array'" class="capabilities-array-val">
                        <template v-if="!entry.items?.length">—</template>
                        <ul v-else-if="entry.items.length <= 12" class="capabilities-chips">
                          <li v-for="item in entry.items" :key="item">{{ item }}</li>
                        </ul>
                        <template v-else>
                          <div class="capabilities-array-summary">
                            <span class="capabilities-count-badge">
                              {{ t('deploymentWorkspace.capabilities.totalItems', { count: entry.items.length }) }}
                            </span>
                            <button
                              type="button"
                              class="capabilities-expand-btn"
                              @click="togglePropertyExpand(entry.rawKey)"
                            >
                              {{ expandedProperties[entry.rawKey]
                                ? t('deploymentWorkspace.capabilities.collapseItems')
                                : t('deploymentWorkspace.capabilities.expandItems', { count: entry.items.length }) }}
                            </button>
                          </div>
                          <ul v-if="expandedProperties[entry.rawKey]" class="capabilities-chips">
                            <li v-for="item in entry.items" :key="item">{{ item }}</li>
                          </ul>
                        </template>
                      </div>
                      <span v-else>{{ entry.textValue }}</span>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>

          <div v-if="capabilities.warnings.length" class="capabilities-group">
            <h4>{{ t('deploymentWorkspace.capabilities.warnings') }}</h4>
            <InlineMessage tone="warning">{{ capabilities.warnings.join('；') }}</InlineMessage>
          </div>
        </div>
      </div>
    </details>

    <template #footer>
      <div class="capabilities-footer">
        <Button variant="secondary" @click="emit('close')">{{ t('common.close') }}</Button>
      </div>
    </template>
  </SideDrawer>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { RefreshCw } from '@lucide/vue'
import { TooltipContent, TooltipPortal, TooltipProvider, TooltipRoot, TooltipTrigger } from 'reka-ui'
import { formatSystemDateTime } from '@/shared/formatters/date-time'
import Button from '@/shared/ui/components/Button.vue'
import SelectField from '@/shared/ui/components/Select.vue'
import SideDrawer from '@/shared/ui/components/SideDrawer.vue'
import StatusBadge from '@/shared/ui/data-display/StatusBadge.vue'
import EmptyState from '@/shared/ui/feedback/EmptyState.vue'
import InlineError from '@/shared/ui/feedback/InlineError.vue'
import InlineMessage from '@/shared/ui/feedback/InlineMessage.vue'
import LoadingPanel from '@/shared/ui/feedback/LoadingPanel.vue'
import { buildDeploymentDeviceOptions } from '../deployment-device-support'
import {
  buildHostCapabilityRows,
  formatDeploymentBackend,
  formatDeploymentDeviceName,
} from '../deployment-presentation'
import { getDeploymentRuntimeCapabilities, type DeploymentRuntimeCapabilities } from '../services/deployment.service'
import DeploymentRuntimeBadge from './DeploymentRuntimeBadge.vue'

interface ReadOnlyPropertyEntry {
  rawKey: string
  label: string
  kind: 'boolean' | 'range' | 'array' | 'text'
  boolValue?: boolean
  items?: string[]
  textValue?: string
}

const props = defineProps<{
  open: boolean
  devices: Record<string, unknown> | null
}>()

const emit = defineEmits<{
  close: []
  'refresh-devices': []
}>()
const { t, te } = useI18n()

function formatFieldLabel(field: string): string {
  const key = `deploymentWorkspace.drawer.runtimeFields.${field}`
  return te(key) ? t(key) : field
}

function formatOsPlatform(raw: unknown): string {
  const text = typeof raw === 'string' ? raw.trim() : ''
  if (!text) return ''
  const lower = text.toLowerCase()
  if (lower === 'win32') return 'Windows x64'
  if (lower === 'macintel') return 'macOS'
  if (lower === 'linux x86_64') return 'Linux x64'
  if (lower === 'linux aarch64') return 'Linux arm64'
  return text
}

const backend = ref('openvino')
const device = ref('CPU')
const loading = ref(false)
const error = ref<string | null>(null)
const capabilities = ref<DeploymentRuntimeCapabilities | null>(null)
const lastUpdatedAt = ref(new Date().toISOString())
const expandedProperties = ref<Record<string, boolean>>({})

const backendOptions = [
  { label: 'OpenVINO', value: 'openvino' },
  { label: 'ONNX Runtime', value: 'onnxruntime' },
  { label: 'TensorRT', value: 'tensorrt' },
  { label: 'PyTorch', value: 'pytorch' },
]

const deviceOptions = computed(() => {
  const opts = buildDeploymentDeviceOptions(props.devices, backend.value, {
    automaticDefault: t('deploymentOps.options.automaticDefault'),
    openvinoAutoDefault: t('deploymentOps.options.openvinoAutoDefault'),
    openvinoGpu: t('deploymentOps.options.openvinoGpu'),
  }).filter(item => item.value)
  return opts.length ? opts : [{ label: 'CPU', value: 'CPU' }]
})

const updatedAtLabel = computed(() => formatSystemDateTime(lastUpdatedAt.value))

const hostSummaryRows = computed(() => {
  const rows: Array<{ label: string; value: string }> = []
  const dev = props.devices ?? {}
  const host = dev.host && typeof dev.host === 'object' ? dev.host as Record<string, unknown> : null
  const cpu = dev.cpu && typeof dev.cpu === 'object' ? dev.cpu as Record<string, unknown> : null

  const osPlatform = formatOsPlatform(host?.os_platform)
    || formatOsPlatform(dev.os)
    || (typeof navigator !== 'undefined' ? formatOsPlatform(navigator.platform) : '')
  if (osPlatform) {
    rows.push({ label: t('deploymentWorkspace.capabilities.osLabel'), value: osPlatform })
  }
  if (typeof host?.os_name === 'string' && host.os_name.trim()) {
    rows.push({ label: t('deploymentWorkspace.capabilities.versionLabel'), value: host.os_name.trim() })
  }
  if (typeof host?.hostname === 'string' && host.hostname.trim()) {
    rows.push({ label: t('deploymentWorkspace.capabilities.hostnameLabel'), value: host.hostname.trim() })
  }
  if (cpu?.physical_cores || cpu?.logical_cores) {
    rows.push({
      label: t('deploymentWorkspace.capabilities.cpuLabel'),
      value: t('deploymentWorkspace.capabilities.cpuFormat', {
        physical: cpu.physical_cores ?? '—',
        logical: cpu.logical_cores ?? '—',
      }),
    })
  }
  return rows
})

const capabilityTableRows = computed(() => buildHostCapabilityRows(props.devices, {
  noDeviceDetected: t('deploymentWorkspace.capabilities.noDeviceDetected'),
  notMacOs: t('deploymentWorkspace.capabilities.notMacOs'),
  notTargetPlatform: t('deploymentWorkspace.capabilities.notTargetPlatform'),
}))

const resultDeviceLabel = computed(() => (
  capabilities.value
    ? (formatDeploymentDeviceName(capabilities.value.device_name) || t('deploymentOps.options.automaticDefault'))
    : ''
))

const resultBadgeTooltip = computed(() => (
  capabilities.value
    ? `${formatDeploymentBackend(capabilities.value.runtime_backend)} · ${resultDeviceLabel.value}`
    : ''
))

const readOnlyEntries = computed<ReadOnlyPropertyEntry[]>(() => {
  const propsRecord = capabilities.value?.read_only_properties ?? {}
  return Object.entries(propsRecord).map(([rawKey, value]) => {
    const upperKey = rawKey.trim().toUpperCase()
    const i18nKey = `deploymentWorkspace.capabilities.properties.${upperKey}`
    const label = te(i18nKey) ? t(i18nKey) : rawKey

    if (typeof value === 'boolean') {
      return { rawKey, label, kind: 'boolean', boolValue: value }
    }
    if (
      Array.isArray(value)
      && value.length === 2
      && value.every(v => typeof v === 'number' || typeof v === 'string')
      && (upperKey.includes('RANGE') || (typeof value[0] === 'number' && typeof value[1] === 'number'))
    ) {
      return { rawKey, label, kind: 'range', textValue: `${value[0]} ~ ${value[1]}` }
    }
    if (value && typeof value === 'object' && !Array.isArray(value) && 'min' in value && 'max' in value) {
      const rangeObj = value as Record<string, unknown>
      return { rawKey, label, kind: 'range', textValue: `${String(rangeObj.min)} ~ ${String(rangeObj.max)}` }
    }
    if (Array.isArray(value)) {
      return {
        rawKey,
        label,
        kind: 'array',
        items: value.map(item => (typeof item === 'object' && item !== null ? JSON.stringify(item) : String(item))),
      }
    }
    return {
      rawKey,
      label,
      kind: 'text',
      textValue: typeof value === 'object' && value !== null ? JSON.stringify(value) : String(value),
    }
  })
})

function togglePropertyExpand(rawKey: string): void {
  expandedProperties.value = {
    ...expandedProperties.value,
    [rawKey]: !expandedProperties.value[rawKey],
  }
}

watch(deviceOptions, (options) => {
  if (!options.some(option => option.value === device.value)) {
    device.value = options[0]?.value ?? 'CPU'
  }
})

watch(() => props.open, (isOpen) => {
  if (isOpen && !capabilities.value && !loading.value) {
    void inspect()
  }
}, { immediate: true })

function setBackend(value: unknown): void {
  backend.value = typeof value === 'string' && value ? value : 'openvino'
  capabilities.value = null
  expandedProperties.value = {}
}

function setDevice(value: unknown): void {
  device.value = typeof value === 'string' && value ? value : 'CPU'
  capabilities.value = null
  expandedProperties.value = {}
}

function refreshAll(): void {
  emit('refresh-devices')
  void inspect()
}

async function inspect(): Promise<void> {
  loading.value = true
  error.value = null
  try {
    capabilities.value = await getDeploymentRuntimeCapabilities(backend.value, device.value)
    expandedProperties.value = {}
    lastUpdatedAt.value = new Date().toISOString()
  } catch (cause) {
    capabilities.value = null
    error.value = cause instanceof Error ? cause.message : t('deploymentOps.messages.capabilitiesFailed')
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
:global(.deployment-capabilities-drawer.side-drawer) {
  width: min(640px, calc(100vw - 36px));
}

.capabilities-meta-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 16px;
  font-size: 13px;
  color: var(--am-text-muted);
}

.capabilities-section {
  display: grid;
  gap: 10px;
  margin-bottom: 18px;
}

.capabilities-section h3,
.capabilities-group h4 {
  margin: 0;
  font-size: 14px;
  font-weight: 700;
}

.capabilities-host-card {
  display: grid;
  gap: 8px;
  margin: 0;
  padding: 12px 16px;
  border: 1px solid var(--am-border);
  border-radius: 8px;
  background: var(--am-surface);
}

.capabilities-host-card > div {
  display: grid;
  grid-template-columns: 96px minmax(0, 1fr);
  gap: 10px;
  font-size: 13px;
  align-items: baseline;
}

.capabilities-host-card dt {
  color: var(--am-text-muted);
}

.capabilities-host-card dd {
  margin: 0;
  font-weight: 500;
  overflow-wrap: anywhere;
}

.capabilities-empty-note {
  margin: 0;
  color: var(--am-text-muted);
  font-size: 13px;
}

.capabilities-table-wrap,
.capabilities-prop-table-wrap {
  border: 1px solid var(--am-border);
  border-radius: 8px;
  overflow-x: auto;
  background: var(--am-surface);
}

.capabilities-table-wrap table,
.capabilities-prop-table {
  width: 100%;
  table-layout: fixed;
  border-collapse: collapse;
}

.capabilities-table-wrap th,
.capabilities-table-wrap td {
  padding: 12px 14px;
  border-bottom: 1px solid var(--am-border);
  text-align: left;
  vertical-align: middle;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.capabilities-table-wrap td.capabilities-backend-td {
  overflow: visible;
  text-overflow: clip;
}

.capabilities-table-wrap tr:last-child td,
.capabilities-prop-table tr:last-child td {
  border-bottom: 0;
}

.capabilities-table-wrap th,
.capabilities-prop-table th {
  color: var(--am-text);
  font-size: 14px;
  font-weight: 600;
  background: var(--am-surface);
}

.capabilities-table-wrap td {
  font-size: 14px;
}

.capabilities-backend-cell {
  position: relative;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 24px;
  vertical-align: middle;
  border-radius: 4px;
}

.capabilities-backend-cell:focus-visible {
  outline: 2px solid var(--am-input-focus-ring);
  outline-offset: 2px;
}

.capability-status {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  white-space: nowrap;
  color: var(--am-text-muted);
}

.capability-status.is-available {
  color: var(--am-action-primary-strong);
  font-weight: 600;
}

.capability-status__dot {
  width: 7px;
  height: 7px;
  border-radius: 999px;
  background: var(--am-neutral-icon);
}

.capability-status.is-available .capability-status__dot {
  background: var(--am-action-primary);
}

.capabilities-notice-box {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 12px 14px;
  border: 1px solid var(--am-warning-border);
  border-radius: 8px;
  background: var(--am-warning-surface);
  color: var(--am-warning-text);
  font-size: 13px;
  margin-bottom: 16px;
}

.capabilities-notice-box__icon {
  flex-shrink: 0;
  margin-top: 2px;
}

.capabilities-notice-box ul {
  margin: 0;
  padding-left: 16px;
  display: grid;
  gap: 4px;
}

.capabilities-probe {
  border: 1px solid var(--am-border);
  border-radius: 8px;
  padding: 10px 12px;
  background: var(--am-surface);
}

.capabilities-probe summary {
  cursor: pointer;
  font-weight: 600;
  font-size: 13px;
}

.capabilities-probe__body {
  display: grid;
  gap: 12px;
  margin-top: 12px;
}

.capabilities-query {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr)) auto;
  gap: 10px;
  align-items: end;
}

.capabilities-result {
  display: grid;
  gap: 12px;
  padding: 12px;
  border: 1px solid var(--am-border);
  border-radius: 6px;
  background: var(--am-surface);
}

.capabilities-result__status {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  font-weight: 600;
}

.capabilities-device-pill {
  display: inline-flex;
  align-items: center;
  padding: 2px 8px;
  border: 1px solid var(--am-border);
  border-radius: 999px;
  background: var(--am-surface);
  font-size: 12px;
  font-weight: 600;
  color: var(--am-text);
}

.capabilities-group {
  display: grid;
  gap: 8px;
}

.capabilities-prop-table th,
.capabilities-prop-table td {
  padding: 9px 12px;
  border-bottom: 1px solid var(--am-border);
  text-align: left;
  vertical-align: top;
}

.capabilities-prop-key {
  color: var(--am-text-muted);
  font-size: 13px;
  font-weight: 500;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.capabilities-prop-val {
  font-size: 13px;
  color: var(--am-text);
  overflow-wrap: anywhere;
}

.capabilities-bool-badge {
  display: inline-flex;
  align-items: center;
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 600;
  white-space: nowrap;
}

.capabilities-bool-badge.is-true {
  background: var(--am-success-surface, rgb(22 163 74 / 0.12));
  color: var(--am-action-primary-strong);
}

.capabilities-bool-badge.is-false {
  border: 1px solid var(--am-border);
  background: var(--am-surface);
  color: var(--am-text-muted);
}

.capabilities-range-value {
  font-variant-numeric: tabular-nums;
  font-weight: 600;
}

.capabilities-array-val {
  display: grid;
  gap: 6px;
}

.capabilities-array-summary {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.capabilities-count-badge {
  display: inline-flex;
  align-items: center;
  padding: 2px 8px;
  border: 1px solid var(--am-border);
  border-radius: 999px;
  background: var(--am-surface);
  font-size: 12px;
  color: var(--am-text-muted);
}

.capabilities-expand-btn {
  padding: 0;
  border: 0;
  background: transparent;
  color: var(--am-action-primary-strong);
  font: inherit;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
}

.capabilities-expand-btn:hover {
  text-decoration: underline;
}

.capabilities-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.capabilities-chips li {
  padding: 2px 8px;
  border: 1px solid var(--am-border);
  border-radius: 4px;
  background: var(--am-surface);
  font-size: 12px;
}

.capabilities-footer {
  display: flex;
  justify-content: flex-end;
  width: 100%;
}

@media (max-width: 600px) {
  .capabilities-query {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>

<style>
.capabilities-backend-tooltip {
  z-index: var(--am-z-tooltip);
  padding: 4px 8px;
  border: 1px solid var(--am-border);
  border-radius: 6px;
  background: var(--am-surface-raised, var(--am-surface));
  color: var(--am-text);
  box-shadow: 0 4px 12px rgb(0 0 0 / 0.12);
  font-size: 12px;
  font-weight: 600;
  line-height: 1.2;
  white-space: nowrap;
  pointer-events: none;
}
</style>
