<template>
  <section class="page-stack">
    <PageHeader :title="t('customNodes.title')">
      <template #actions>
        <Button variant="secondary" :disabled="loading" :loading="loading" @click="loadCatalog">
          <RefreshCw :size="16" />
          {{ t('common.refresh') }}
        </Button>
      </template>
    </PageHeader>

    <InlineError :message="errorMessage" />

    <TabList
      class="custom-node-catalog__tabs"
      :model-value="activeTab"
      :tabs="tabs"
      :label="t('customNodes.title')"
      @update:model-value="selectTab"
    />

    <section v-if="activeTab === 'nodes'" class="catalog-workbench">
      <div class="catalog-workbench__main">
        <div class="catalog-toolbar">
          <label class="input-with-icon catalog-toolbar__search">
            <Search :size="16" />
            <input
              v-model="keyword"
              :aria-label="t('customNodes.fields.keyword')"
              :placeholder="t('customNodes.searchPlaceholder')"
            />
          </label>

          <div class="catalog-toolbar__actions">
            <details class="catalog-filter-menu">
              <summary class="ui-button ui-button--secondary ui-button--md">
                <ListFilter :size="16" />
                {{ t('customNodes.actions.filters') }}
                <span v-if="activeFilterCount" class="catalog-filter-menu__count">{{ activeFilterCount }}</span>
              </summary>
              <div class="catalog-filter-menu__panel">
                <label class="field">
                  <span>{{ t('customNodes.fields.source') }}</span>
                  <SelectField :model-value="sourceFilter" :options="sourceOptions" @update:model-value="setSourceFilter" />
                </label>
                <label class="field">
                  <span>{{ t('customNodes.fields.category') }}</span>
                  <SelectField :model-value="categoryFilter" :options="categoryOptions" @update:model-value="setCategoryFilter" />
                </label>
                <label class="field">
                  <span>{{ t('customNodes.fields.nodePack') }}</span>
                  <SelectField :model-value="nodePackFilter" :options="nodePackOptions" @update:model-value="setNodePackFilter" />
                </label>
                <label class="field">
                  <span>{{ t('customNodes.fields.payloadType') }}</span>
                  <SelectField :model-value="payloadFilter" :options="payloadOptions" @update:model-value="setPayloadFilter" />
                </label>
                <label class="field">
                  <span>{{ t('customNodes.fields.capability') }}</span>
                  <SelectField :model-value="capabilityFilter" :options="capabilityOptions" @update:model-value="setCapabilityFilter" />
                </label>
                <label class="field">
                  <span>{{ t('customNodes.fields.runtimeKind') }}</span>
                  <SelectField :model-value="runtimeKindFilter" :options="runtimeKindOptions" @update:model-value="setRuntimeKindFilter" />
                </label>
                <Button size="sm" variant="ghost" :disabled="activeFilterCount === 0" @click.prevent="clearNodeFilters">
                  {{ t('customNodes.actions.clearFilters') }}
                </Button>
              </div>
            </details>
            <span class="catalog-toolbar__result">{{ filteredNodes.length }}</span>
          </div>
        </div>

        <EmptyState
          v-if="!loading && filteredNodes.length === 0"
          :title="t('customNodes.emptyTitle')"
          :description="t('customNodes.emptyDescription')"
        />

        <div v-else>
          <div class="resource-table custom-node-catalog__table">
            <table>
              <thead>
                <tr>
                  <th>{{ t('customNodes.columns.node') }}</th>
                  <th>{{ t('customNodes.columns.category') }}</th>
                  <th>{{ t('customNodes.columns.source') }}</th>
                  <th>{{ t('customNodes.columns.ports') }}</th>
                  <th>{{ t('customNodes.fields.version') }}</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="node in filteredNodes"
                  :key="node.node_type_id"
                  :class="{ 'is-selected': selectedNode?.node_type_id === node.node_type_id }"
                  :aria-selected="selectedNode?.node_type_id === node.node_type_id"
                  tabindex="0"
                  @click="selectNode(node)"
                  @keydown.enter="selectNode(node)"
                  @keydown.space.prevent="selectNode(node)"
                >
                  <td>
                    <strong>{{ readNodeDisplayName(node) || node.node_type_id }}</strong>
                    <span>{{ node.node_type_id }}</span>
                  </td>
                  <td>{{ node.category || '-' }}</td>
                  <td>{{ readNodeSource(node) }}</td>
                  <td>{{ node.input_ports.length }} / {{ node.output_ports.length }}</td>
                  <td>{{ node.node_pack_version || '-' }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <aside v-if="selectedNode" class="node-catalog-inspector" :aria-label="t('customNodes.detail.title')">
        <div class="node-catalog-inspector__header">
          <div>
            <h2>{{ readNodeDisplayName(selectedNode) || selectedNode.node_type_id }}</h2>
            <p>{{ readNodeDescription(selectedNode) || t('common.noValue') }}</p>
          </div>
          <Button icon-only size="sm" variant="ghost" :aria-label="t('common.close')" @click="closeNodeDetails">
            <X :size="17" />
          </Button>
        </div>

        <dl class="node-catalog-inspector__facts">
          <div>
            <dt>{{ t('customNodes.fields.nodeTypeId') }}</dt>
            <dd><code>{{ selectedNode.node_type_id }}</code></dd>
          </div>
          <div>
            <dt>{{ t('customNodes.fields.category') }}</dt>
            <dd>{{ selectedNode.category || '-' }}</dd>
          </div>
          <div>
            <dt>{{ t('customNodes.fields.source') }}</dt>
            <dd>{{ readNodeSource(selectedNode) }}</dd>
          </div>
          <div>
            <dt>{{ t('customNodes.fields.version') }}</dt>
            <dd>{{ selectedNode.node_pack_version || '-' }}</dd>
          </div>
          <div>
            <dt>{{ t('customNodes.fields.capabilityTags') }}</dt>
            <dd>{{ selectedNode.capability_tags.length ? selectedNode.capability_tags.join(', ') : '-' }}</dd>
          </div>
        </dl>

        <section class="node-catalog-inspector__section">
          <h3>{{ t('customNodes.detail.inputs') }}</h3>
          <PortList :ports="selectedNode.input_ports" />
        </section>
        <section class="node-catalog-inspector__section">
          <h3>{{ t('customNodes.detail.outputs') }}</h3>
          <PortList :ports="selectedNode.output_ports" />
        </section>
        <section v-if="parameterFields.length" class="node-catalog-inspector__section">
          <h3>{{ t('customNodes.detail.parameters') }}</h3>
          <div class="parameter-list">
            <article v-for="field in parameterFields" :key="field.parameter_name">
              <strong>{{ field.parameter_name }}</strong>
              <span>{{ readParameterDisplayName(field) }} / {{ field.required ? t('customNodes.required') : t('customNodes.optional') }}</span>
              <small>{{ t('customNodes.fields.defaultValue') }}: {{ formatValue(field.default_value) }}</small>
              <p v-if="readParameterDescription(field)">{{ readParameterDescription(field) }}</p>
            </article>
          </div>
        </section>
        <details class="node-catalog-inspector__runtime">
          <summary>{{ t('customNodes.detail.runtimeInformation') }}</summary>
          <dl>
            <div>
              <dt>{{ t('customNodes.fields.implementationKind') }}</dt>
              <dd><code>{{ selectedNode.implementation_kind }}</code></dd>
            </div>
            <div>
              <dt>{{ t('customNodes.fields.runtimeKind') }}</dt>
              <dd><code>{{ selectedNode.runtime_kind }}</code></dd>
            </div>
          </dl>
          <pre class="json-view custom-node-catalog__json">{{ formatJson(selectedNode.runtime_requirements) }}</pre>
        </details>
      </aside>
    </section>

    <section v-else-if="activeTab === 'packs'" class="node-pack-workbench">
      <div class="resource-table node-pack-workbench__table">
        <table>
          <thead>
            <tr>
              <th>{{ t('customNodes.columns.pack') }}</th>
              <th>{{ t('customNodes.columns.status') }}</th>
              <th>{{ t('customNodes.fields.nodeCount') }}</th>
              <th>{{ t('customNodes.fields.dependencies') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="pack in nodePackRows"
              :key="pack.id"
              :class="{ 'is-selected': selectedNodePackId === pack.id }"
              @click="selectNodePack(pack.id)"
            >
              <td>
                <strong>{{ pack.displayName }}</strong>
                <span>{{ pack.id }} / {{ pack.version }}</span>
              </td>
              <td>
                <StatusBadge :tone="pack.statusTone">{{ pack.statusLabel }}</StatusBadge>
                <span>{{ pack.category }}</span>
              </td>
              <td>{{ pack.nodeCount }}</td>
              <td>{{ pack.dependencySummary }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <aside v-if="selectedNodePackRow" class="node-catalog-inspector" :aria-label="t('customNodes.tabs.packs')">
          <div class="node-catalog-inspector__header">
            <div>
              <h2>{{ selectedNodePackRow.displayName }}</h2>
              <p>{{ selectedNodePackRow.description }}</p>
            </div>
            <Button icon-only size="sm" variant="ghost" :aria-label="t('common.close')" @click="selectedNodePackId = null">
              <X :size="17" />
            </Button>
          </div>

          <StatusBadge :tone="selectedNodePackRow.statusTone">{{ selectedNodePackRow.statusLabel }}</StatusBadge>

          <div class="node-pack-actions">
            <Button size="sm" variant="secondary" :disabled="loading || actionKey !== null" @click="reloadCatalogFromLoader">
              <RefreshCw :size="15" />
              {{ t('customNodes.actions.reload') }}
            </Button>
            <Button
              size="sm"
              variant="secondary"
              :disabled="loading || actionKey !== null"
              @click="validateSelectedNodePack(selectedNodePackRow.id)"
            >
              <CircleCheck :size="15" />
              {{ t('customNodes.actions.validate') }}
            </Button>
            <Button
              v-if="!selectedNodePackRow.enabled"
              size="sm"
              variant="primary"
              :disabled="loading || actionKey !== null"
              @click="enableSelectedNodePack(selectedNodePackRow.id)"
            >
              <Power :size="15" />
              {{ t('customNodes.actions.enable') }}
            </Button>
            <Button
              v-else
              size="sm"
              variant="danger"
              :disabled="loading || actionKey !== null"
              @click="disableSelectedNodePack(selectedNodePackRow.id)"
            >
              <PowerOff :size="15" />
              {{ t('customNodes.actions.disable') }}
            </Button>
            <Button
              size="sm"
              variant="ghost"
              :disabled="loading || actionKey !== null"
              @click="showNodePackLogs(selectedNodePackRow.id)"
            >
              <ScrollText :size="15" />
              {{ t('customNodes.actions.logs') }}
            </Button>
          </div>

          <dl class="detail-list">
            <div v-for="item in selectedNodePackDetails" :key="item.key">
              <dt>{{ item.label }}</dt>
              <dd>{{ item.value }}</dd>
            </div>
          </dl>

          <section class="node-detail-panel__section">
            <h3>{{ t('customNodes.detail.dependencies') }}</h3>
            <div v-if="selectedNodePackDependencies.length" class="dependency-list">
              <article v-for="dependency in selectedNodePackDependencies" :key="dependency.key">
                <strong>{{ dependency.nodePackId }}</strong>
                <span>{{ dependency.versionRange }}</span>
                <StatusBadge :tone="dependency.satisfied ? 'success' : 'warning'">
                  {{ dependency.satisfied ? t('customNodes.status.available') : t('customNodes.status.missing') }}
                </StatusBadge>
              </article>
            </div>
            <p v-else class="result-note">{{ t('customNodes.messages.noDependencies') }}</p>
          </section>

          <section v-if="visibleLogsPackId === selectedNodePackRow.id" class="node-detail-panel__section">
            <h3>{{ t('customNodes.detail.logs') }}</h3>
            <div v-if="selectedNodePackLogs.length" class="node-pack-log-list">
              <article v-for="(log, index) in selectedNodePackLogs" :key="`${log.created_at}:${index}`">
                <StatusBadge :tone="log.level === 'error' ? 'danger' : log.level === 'warning' ? 'warning' : 'neutral'">
                  {{ log.level }}
                </StatusBadge>
                <div>
                  <strong>{{ log.message }}</strong>
                  <span>{{ log.created_at }}</span>
                  <small>{{ formatJson(log.details) }}</small>
                </div>
              </article>
            </div>
            <p v-else class="result-note">{{ t('customNodes.messages.noLogs') }}</p>
          </section>

          <details class="node-catalog-inspector__runtime">
            <summary>{{ t('customNodes.detail.manifestJson') }}</summary>
            <pre class="json-view custom-node-catalog__json">{{ formatJson(selectedNodePackRow.manifest) }}</pre>
          </details>
      </aside>
    </section>

    <section v-else class="node-diagnostics-workbench">
      <EmptyState
        v-if="diagnosticIssues.length === 0"
        :title="t('customNodes.messages.noIssuesTitle')"
        :description="t('customNodes.messages.noIssuesDescription')"
      />

      <div v-else class="resource-table node-diagnostics-workbench__table">
        <table>
          <thead>
            <tr>
              <th>{{ t('customNodes.columns.status') }}</th>
              <th>{{ t('customNodes.columns.pack') }}</th>
              <th>{{ t('customNodes.columns.issue') }}</th>
              <th>{{ t('customNodes.columns.detail') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="issue in diagnosticIssues" :key="issue.id">
              <td><StatusBadge :tone="issue.tone">{{ issue.level }}</StatusBadge></td>
              <td>{{ issue.packId }}</td>
              <td>{{ issue.title }}</td>
              <td>{{ issue.detail }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  </section>
</template>

<script setup lang="ts">
import { computed, defineComponent, h, onMounted, ref, watch, type PropType } from 'vue'
import { CircleCheck, ListFilter, Power, PowerOff, RefreshCw, ScrollText, Search, X } from '@lucide/vue'
import { useI18n } from 'vue-i18n'

import type { SupportedLocale } from '@/platform/i18n'
import { getWorkflowNodeCatalog } from '@/workflows/workflow-editor/services/node-catalog.service'
import {
  resolveNodeDefinitionDescription,
  resolveNodeDefinitionDisplayName,
  resolveNodeParameterDescription,
  resolveNodeParameterDisplayName,
  resolveNodePortDescription,
} from '@/workflows/workflow-editor/node-definition-localization'
import {
  disableNodePack,
  enableNodePack,
  getNodePackLogs,
  getNodePackStatus,
  reloadNodePacks,
  validateNodePack,
  type NodePackStatusItem,
  type NodePackStatusLog,
  type NodePackStatusResponse,
} from '../services/node-pack-status.service'
import type {
  NodeDefinition,
  NodeParameterUiField,
  NodePortDefinition,
  WorkflowNodeCatalogResponse,
  WorkflowNodePackManifest,
} from '@/workflows/workflow-editor/types'
import Button from '@/shared/ui/components/Button.vue'
import SelectField from '@/shared/ui/components/Select.vue'
import StatusBadge from '@/shared/ui/data-display/StatusBadge.vue'
import EmptyState from '@/shared/ui/feedback/EmptyState.vue'
import InlineError from '@/shared/ui/feedback/InlineError.vue'
import PageHeader from '@/shared/ui/layout/PageHeader.vue'
import TabList from '@/shared/ui/navigation/TabList.vue'

type SelectValue = string | number | boolean | null
type CatalogTabId = 'nodes' | 'packs' | 'diagnostics'
type BadgeTone = 'neutral' | 'success' | 'warning' | 'danger' | 'info'

interface NodePackOption {
  id: string
  displayName: string
}

interface NodePackDetailItem {
  key: string
  label: string
  value: string
}

interface NodePackDependency {
  key: string
  nodePackId: string
  versionRange: string
  installed: boolean
  enabled: boolean
  satisfied: boolean
}

interface NodePackStatusRow {
  id: string
  displayName: string
  description: string
  version: string
  category: string
  statusTone: BadgeTone
  statusLabel: string
  state: string
  enabled: boolean
  nodeCount: number
  capabilitySummary: string
  dependencySummary: string
  permissionScopeSummary: string
  sourceDir: string
  manifestPath: string
  catalogPath: string
  loadedAt: string
  manifest: WorkflowNodePackManifest | null
  dependencies: NodePackDependency[]
  issues: NodePackStatusItem['issues']
  logs: NodePackStatusLog[]
}

interface CatalogTabItem {
  id: CatalogTabId
  label: string
  count: number
}

interface DiagnosticIssue {
  id: string
  packId: string
  level: string
  tone: BadgeTone
  title: string
  detail: string
}

const PortList = defineComponent({
  props: {
    ports: {
      type: Array as PropType<NodePortDefinition[]>,
      required: true,
    },
  },
  setup(props) {
    const { t, locale } = useI18n()
    const currentLocale = computed(() => (typeof locale.value === 'string' ? locale.value : 'en-US') as SupportedLocale)
    return () =>
      props.ports.length === 0
        ? h('p', { class: 'result-note' }, '-')
        : h(
            'div',
            { class: 'port-list' },
            props.ports.map((port) =>
              h('article', { key: port.name }, [
                h('strong', port.name),
                h('span', `${port.payload_type_id} / ${port.required ? t('customNodes.required') : t('customNodes.optional')}`),
                resolveNodePortDescription(port, currentLocale.value) ? h('p', resolveNodePortDescription(port, currentLocale.value)) : null,
                h('small', port.required ? t('customNodes.required') : t('customNodes.optional')),
              ]),
            ),
          )
  },
})

const { t, locale } = useI18n()
const currentLocale = computed(() => (typeof locale.value === 'string' ? locale.value : 'en-US') as SupportedLocale)
const catalog = ref<WorkflowNodeCatalogResponse | null>(null)
const nodePackStatus = ref<NodePackStatusResponse | null>(null)
const loading = ref(false)
const actionKey = ref<string | null>(null)
const errorMessage = ref<string | null>(null)
const keyword = ref('')
const runtimeKindFilter = ref('all')
const sourceFilter = ref('all')
const categoryFilter = ref('all')
const nodePackFilter = ref('all')
const payloadFilter = ref('all')
const capabilityFilter = ref('all')
const activeTab = ref<CatalogTabId>('nodes')
const selectedNode = ref<NodeDefinition | null>(null)
const selectedNodePackId = ref<string | null>(null)
const visibleLogsPackId = ref<string | null>(null)
const selectedNodePackLogs = ref<NodePackStatusLog[]>([])

const allNodes = computed(() => catalog.value?.node_definitions ?? [])
const runtimeKindOptions = computed(() => {
  const runtimeKinds = Array.from(new Set(allNodes.value.map((node) => node.runtime_kind).filter(Boolean))).sort((left, right) =>
    left.localeCompare(right),
  )
  return [{ label: t('customNodes.runtimeOptions.all'), value: 'all' }, ...runtimeKinds.map((kind) => ({ label: kind, value: kind }))]
})
const sourceOptions = computed(() => [
  { label: t('customNodes.filterOptions.all'), value: 'all' },
  { label: t('customNodes.sourceOptions.core'), value: 'core-node' },
  { label: t('customNodes.sourceOptions.custom'), value: 'custom-node' },
])
const categoryOptions = computed(() => [
  { label: t('customNodes.filterOptions.all'), value: 'all' },
  ...Array.from(new Set(allNodes.value.map((node) => node.category).filter(Boolean)))
    .sort((left, right) => left.localeCompare(right))
    .map((category) => ({ label: category, value: category })),
])
const payloadTypes = computed(() => catalog.value?.payload_contracts ?? [])
const capabilityTags = computed(() =>
  Array.from(new Set(allNodes.value.flatMap((node) => node.capability_tags))).sort((left, right) => left.localeCompare(right)),
)
const nodePacks = computed<NodePackOption[]>(() => {
  const packMap = new Map<string, NodePackOption>()
  for (const manifest of catalog.value?.node_pack_manifests ?? []) {
    const packId = readStringField(manifest, 'node_pack_id', 'pack_id', 'id', 'name')
    if (!packId) continue
    packMap.set(packId, {
      id: packId,
      displayName: readStringField(manifest, 'display_name', 'displayName', 'name') ?? packId,
    })
  }

  for (const item of nodePackStatus.value?.items ?? []) {
    packMap.set(item.node_pack_id, {
      id: item.node_pack_id,
      displayName: item.display_name || item.node_pack_id,
    })
  }

  for (const packId of allNodes.value
    .map((node) => node.node_pack_id)
    .filter((value): value is string => typeof value === 'string' && value.length > 0)
  ) {
    if (!packMap.has(packId)) {
      packMap.set(packId, { id: packId, displayName: packId })
    }
  }
  return Array.from(packMap.values()).sort((left, right) => left.displayName.localeCompare(right.displayName))
})
const nodePackOptions = computed(() => [
  { label: t('customNodes.filterOptions.all'), value: 'all' },
  ...nodePacks.value.map((pack) => ({ label: pack.displayName, value: pack.id })),
])
const payloadOptions = computed(() => [
  { label: t('customNodes.filterOptions.all'), value: 'all' },
  ...payloadTypes.value.map((payload) => ({ label: payload.display_name || payload.payload_type_id, value: payload.payload_type_id })),
])
const capabilityOptions = computed(() => [
  { label: t('customNodes.filterOptions.all'), value: 'all' },
  ...capabilityTags.value.map((tag) => ({ label: tag, value: tag })),
])
const activeFilterCount = computed(
  () =>
    [sourceFilter, categoryFilter, nodePackFilter, payloadFilter, capabilityFilter, runtimeKindFilter].filter(
      (filter) => filter.value !== 'all',
    ).length,
)
const nodePackRows = computed<NodePackStatusRow[]>(() =>
  nodePacks.value.map((pack) => buildNodePackStatusRow(pack)).sort((left, right) => left.displayName.localeCompare(right.displayName)),
)
const diagnosticIssues = computed<DiagnosticIssue[]>(() => buildDiagnosticIssues())
const tabs = computed<CatalogTabItem[]>(() => [
  { id: 'nodes', label: t('customNodes.tabs.nodes'), count: allNodes.value.length },
  { id: 'packs', label: t('customNodes.tabs.packs'), count: nodePackRows.value.length },
  { id: 'diagnostics', label: t('customNodes.tabs.diagnostics'), count: diagnosticIssues.value.length },
])

const filteredNodes = computed(() => {
  const normalizedKeyword = keyword.value.trim().toLowerCase()
  return allNodes.value.filter((node) => {
    if (runtimeKindFilter.value !== 'all' && node.runtime_kind !== runtimeKindFilter.value) return false
    if (sourceFilter.value !== 'all' && node.implementation_kind !== sourceFilter.value) return false
    if (categoryFilter.value !== 'all' && node.category !== categoryFilter.value) return false
    if (nodePackFilter.value !== 'all' && node.node_pack_id !== nodePackFilter.value) return false
    if (
      payloadFilter.value !== 'all' &&
      ![...node.input_ports, ...node.output_ports].some((port) => port.payload_type_id === payloadFilter.value)
    )
      return false
    if (capabilityFilter.value !== 'all' && !node.capability_tags.includes(capabilityFilter.value)) return false
    if (!normalizedKeyword) return true
    return [
      node.node_type_id,
      readNodeDisplayName(node),
      node.category,
      readNodeDescription(node),
      node.node_pack_id ?? '',
      node.node_pack_version ?? '',
      ...node.capability_tags,
      ...node.input_ports.map((port) => port.payload_type_id),
      ...node.output_ports.map((port) => port.payload_type_id),
    ]
      .join(' ')
      .toLowerCase()
      .includes(normalizedKeyword)
  })
})

const parameterFields = computed<NodeParameterUiField[]>(() => selectedNode.value?.parameter_ui_schema?.fields ?? [])
const selectedNodePackRow = computed(() => {
  if (!selectedNodePackId.value) return null
  return nodePackRows.value.find((pack) => pack.id === selectedNodePackId.value) ?? null
})
const selectedNodePackDependencies = computed(() => selectedNodePackRow.value?.dependencies ?? [])
const selectedNodePackDetails = computed<NodePackDetailItem[]>(() => {
  const row = selectedNodePackRow.value
  if (!row) return []
  return [
    { key: 'id', label: t('customNodes.fields.nodePackId'), value: row.id },
    { key: 'version', label: t('customNodes.fields.version'), value: row.version },
    { key: 'category', label: t('customNodes.fields.category'), value: row.category },
    { key: 'status', label: t('customNodes.fields.loadStatus'), value: row.statusLabel },
    { key: 'enabled', label: t('customNodes.fields.enabledByDefault'), value: formatBoolean(row.enabled) },
    { key: 'node-count', label: t('customNodes.fields.nodeCount'), value: String(row.nodeCount) },
    { key: 'source-dir', label: t('customNodes.fields.sourceDir'), value: row.sourceDir },
    { key: 'manifest-path', label: t('customNodes.fields.manifestPath'), value: row.manifestPath },
    { key: 'loaded-at', label: t('customNodes.fields.loadedAt'), value: row.loadedAt },
    { key: 'capabilities', label: t('customNodes.fields.capabilityTags'), value: row.capabilitySummary },
    { key: 'dependencies', label: t('customNodes.fields.dependencies'), value: row.dependencySummary },
    { key: 'permissions', label: t('customNodes.fields.permissionScopes'), value: row.permissionScopeSummary },
    { key: 'entrypoints', label: t('customNodes.fields.entrypoints'), value: row.manifest ? formatListValue(readManifestValue(row.manifest, 'entrypoints')) : '-' },
    { key: 'catalog-path', label: t('customNodes.fields.catalogPath'), value: row.catalogPath },
  ]
})

onMounted(() => {
  void loadCatalog()
})

watch(filteredNodes, (nodes) => {
  if (selectedNode.value && !nodes.some((node) => node.node_type_id === selectedNode.value?.node_type_id)) {
    selectedNode.value = null
  }
})

watch(runtimeKindOptions, (options) => {
  if (!options.some((option) => option.value === runtimeKindFilter.value)) {
    runtimeKindFilter.value = 'all'
  }
})

watch(nodePackRows, (rows) => {
  if (selectedNodePackId.value && !rows.some((pack) => pack.id === selectedNodePackId.value)) {
    selectedNodePackId.value = null
  }
})

watch(selectedNodePackId, () => {
  visibleLogsPackId.value = null
  selectedNodePackLogs.value = []
})

async function loadCatalog(): Promise<void> {
  loading.value = true
  errorMessage.value = null
  try {
    const [catalogResponse, statusResponse] = await Promise.all([getWorkflowNodeCatalog({}), getNodePackStatus()])
    catalog.value = catalogResponse
    nodePackStatus.value = statusResponse
    selectedNode.value = null
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : t('customNodes.messages.loadFailed')
  } finally {
    loading.value = false
  }
}

async function reloadCatalogFromLoader(): Promise<void> {
  await runNodePackAction('reload', async () => reloadNodePacks())
}

async function validateSelectedNodePack(packId: string): Promise<void> {
  await runNodePackAction(`validate:${packId}`, async () => validateNodePack(packId))
}

async function enableSelectedNodePack(packId: string): Promise<void> {
  await runNodePackAction(`enable:${packId}`, async () => enableNodePack(packId))
}

async function disableSelectedNodePack(packId: string): Promise<void> {
  await runNodePackAction(`disable:${packId}`, async () => disableNodePack(packId))
}

async function showNodePackLogs(packId: string): Promise<void> {
  actionKey.value = `logs:${packId}`
  errorMessage.value = null
  try {
    selectedNodePackLogs.value = await getNodePackLogs(packId)
    visibleLogsPackId.value = packId
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : t('customNodes.messages.actionFailed')
  } finally {
    actionKey.value = null
  }
}

async function runNodePackAction(action: string, runner: () => Promise<NodePackStatusResponse>): Promise<void> {
  actionKey.value = action
  errorMessage.value = null
  try {
    nodePackStatus.value = await runner()
    const [catalogResponse, statusResponse] = await Promise.all([getWorkflowNodeCatalog({}), getNodePackStatus()])
    catalog.value = catalogResponse
    nodePackStatus.value = statusResponse
    selectedNode.value = null
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : t('customNodes.messages.actionFailed')
  } finally {
    actionKey.value = null
  }
}

function selectNode(node: NodeDefinition): void {
  selectedNode.value = node
}

function closeNodeDetails(): void {
  selectedNode.value = null
}

function selectTab(tabId: string): void {
  if (tabId === 'nodes' || tabId === 'packs' || tabId === 'diagnostics') {
    activeTab.value = tabId
    selectedNode.value = null
    selectedNodePackId.value = null
  }
}

function selectNodePack(packId: string): void {
  selectedNodePackId.value = packId
}

function setRuntimeKindFilter(value: SelectValue): void {
  runtimeKindFilter.value = typeof value === 'string' ? value : 'all'
}

function setSourceFilter(value: SelectValue): void {
  sourceFilter.value = typeof value === 'string' ? value : 'all'
}

function setCategoryFilter(value: SelectValue): void {
  categoryFilter.value = typeof value === 'string' ? value : 'all'
}

function setNodePackFilter(value: SelectValue): void {
  nodePackFilter.value = typeof value === 'string' ? value : 'all'
}

function setPayloadFilter(value: SelectValue): void {
  payloadFilter.value = typeof value === 'string' ? value : 'all'
}

function setCapabilityFilter(value: SelectValue): void {
  capabilityFilter.value = typeof value === 'string' ? value : 'all'
}

function clearNodeFilters(): void {
  sourceFilter.value = 'all'
  categoryFilter.value = 'all'
  nodePackFilter.value = 'all'
  payloadFilter.value = 'all'
  capabilityFilter.value = 'all'
  runtimeKindFilter.value = 'all'
}

function readNodeSource(node: NodeDefinition): string {
  if (node.node_pack_id) return node.node_pack_id
  return node.implementation_kind === 'custom-node' ? t('customNodes.sourceOptions.custom') : t('customNodes.sourceOptions.core')
}

function countByPack(packId: string): number {
  return allNodes.value.filter((node) => node.node_pack_id === packId).length
}

function buildNodePackStatusRow(pack: NodePackOption): NodePackStatusRow {
  const statusItem = findNodePackStatus(pack.id)
  const manifest = statusItem?.manifest ?? findNodePackManifest(pack.id)
  const nodeCount = statusItem?.node_count ?? countByPack(pack.id)
  const dependencies = statusItem ? readStatusDependencies(statusItem) : manifest ? readManifestDependencies(manifest) : []
  const statusTone = getNodePackStatusTone(statusItem)
  const statusLabel = getNodePackStatusLabel(statusItem, manifest, dependencies, nodeCount)
  return {
    id: pack.id,
    displayName: statusItem?.display_name || pack.displayName,
    description: manifest ? readManifestText(manifest, 'description') : '-',
    version: statusItem?.version ?? (manifest ? readManifestText(manifest, 'version') : '-'),
    category: manifest ? readManifestText(manifest, 'category') : '-',
    statusTone,
    statusLabel,
    state: statusItem?.state ?? 'unknown',
    enabled: statusItem?.enabled ?? (manifest ? readManifestValue(manifest, 'enabledByDefault', 'enabled_by_default') === true : false),
    nodeCount,
    capabilitySummary: statusItem ? formatListValue(statusItem.capabilities) : manifest ? formatListValue(readManifestValue(manifest, 'capabilities')) : '-',
    dependencySummary: dependencies.length
      ? dependencies.map((dependency) => `${dependency.nodePackId} ${dependency.versionRange}`.trim()).join(', ')
      : '-',
    permissionScopeSummary: statusItem
      ? formatListValue(statusItem.permission_scopes)
      : manifest
        ? formatListValue(readManifestValue(manifest, 'permissionScopes', 'permission_scopes'))
        : '-',
    sourceDir: statusItem?.source_dir ?? '-',
    manifestPath: statusItem?.manifest_path ?? '-',
    catalogPath: statusItem?.custom_node_catalog_path ?? (manifest ? readManifestText(manifest, 'customNodeCatalogPath', 'custom_node_catalog_path') : '-'),
    loadedAt: statusItem?.loaded_at ?? '-',
    manifest,
    dependencies,
    issues: statusItem?.issues ?? [],
    logs: statusItem?.logs ?? [],
  }
}

function buildDiagnosticIssues(): DiagnosticIssue[] {
  const issues: DiagnosticIssue[] = []
  for (const pack of nodePackRows.value) {
    for (const issue of pack.issues) {
      issues.push({
        id: `${pack.id}:${issue.code}`,
        packId: pack.id,
        level: issue.severity,
        tone: issue.severity === 'error' ? 'danger' : issue.severity === 'warning' ? 'warning' : 'neutral',
        title: issue.message,
        detail: formatIssueDetails(issue.details),
      })
    }
  }
  return issues
}

function findNodePackStatus(packId: string): NodePackStatusItem | null {
  return nodePackStatus.value?.items.find((item) => item.node_pack_id === packId) ?? null
}

function readStatusDependencies(statusItem: NodePackStatusItem): NodePackDependency[] {
  return statusItem.dependencies.map((dependency, index) => ({
    key: `${dependency.node_pack_id}:${index}`,
    nodePackId: dependency.node_pack_id,
    versionRange: dependency.version_range ?? '-',
    installed: dependency.installed,
    enabled: dependency.enabled,
    satisfied: dependency.satisfied,
  }))
}

function getNodePackStatusTone(statusItem: NodePackStatusItem | null): BadgeTone {
  if (!statusItem) return 'warning'
  if (statusItem.state === 'failed') return 'danger'
  if (statusItem.issues.some((issue) => issue.severity === 'error')) return 'danger'
  if (statusItem.state === 'disabled') return 'neutral'
  if (statusItem.issues.some((issue) => issue.severity === 'warning')) return 'warning'
  return 'success'
}

function getNodePackStatusLabel(
  statusItem: NodePackStatusItem | null,
  manifest: WorkflowNodePackManifest | null,
  dependencies: NodePackDependency[],
  nodeCount: number,
): string {
  if (statusItem?.state === 'failed') return t('customNodes.status.failed')
  if (statusItem?.state === 'disabled') return t('customNodes.status.disabled')
  if (statusItem?.state === 'loaded') {
    if (statusItem.issues.some((issue) => issue.severity === 'warning')) return t('customNodes.status.warning')
    return t('customNodes.status.loaded')
  }
  if (!manifest) return t('customNodes.status.manifestMissing')
  if (dependencies.some((dependency) => !dependency.satisfied)) return t('customNodes.status.dependencyMissing')
  if (nodeCount === 0) return t('customNodes.status.noNodes')
  return t('customNodes.status.loaded')
}

function formatIssueDetails(details: Record<string, unknown>): string {
  const entries = Object.entries(details).filter(([, value]) => value !== null && value !== undefined && value !== '')
  if (entries.length === 0) return '-'
  return entries.map(([key, value]) => `${key}: ${formatValue(value)}`).join(' / ')
}

function formatJson(value: unknown): string {
  return JSON.stringify(value ?? {}, null, 2)
}

function readNodeDisplayName(node: NodeDefinition): string {
  return resolveNodeDefinitionDisplayName(node, currentLocale.value)
}

function readNodeDescription(node: NodeDefinition): string {
  return resolveNodeDefinitionDescription(node, currentLocale.value)
}

function readParameterDisplayName(field: NodeParameterUiField): string {
  return resolveNodeParameterDisplayName(field, currentLocale.value)
}

function readParameterDescription(field: NodeParameterUiField): string {
  return resolveNodeParameterDescription(field, currentLocale.value)
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined || value === '') return '-'
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') return String(value)
  return JSON.stringify(value)
}

function readStringField(source: WorkflowNodePackManifest, ...fieldNames: string[]): string | null {
  for (const fieldName of fieldNames) {
    const value = source[fieldName]
    if (typeof value === 'string' && value.length > 0) return value
  }
  return null
}

function findNodePackManifest(packId: string): WorkflowNodePackManifest | null {
  return (
    (catalog.value?.node_pack_manifests ?? []).find((manifest) => readStringField(manifest, 'node_pack_id', 'pack_id', 'id', 'name') === packId) ??
    null
  )
}

function readManifestValue(source: WorkflowNodePackManifest, ...fieldNames: string[]): unknown {
  for (const fieldName of fieldNames) {
    const value = source[fieldName]
    if (value !== undefined && value !== null && value !== '') return value
  }
  return null
}

function readManifestDependencies(source: WorkflowNodePackManifest): NodePackDependency[] {
  const dependencies = readManifestValue(source, 'dependencies')
  if (!Array.isArray(dependencies)) return []
  return dependencies
    .map((item, index) => {
      if (typeof item === 'string') {
        return buildDependency(item, '-', index)
      }
      if (typeof item === 'object' && item !== null) {
        const record = item as Record<string, unknown>
        const nodePackId = stringValue(record.nodePackId ?? record.node_pack_id ?? record.pack_id ?? record.id)
        if (nodePackId === '-') return null
        return buildDependency(nodePackId, stringValue(record.versionRange ?? record.version_range ?? record.version), index)
      }
      return null
    })
    .filter((item): item is NodePackDependency => item !== null)
}

function buildDependency(nodePackId: string, versionRange: string, index: number): NodePackDependency {
  const installed = nodePacks.value.some((pack) => pack.id === nodePackId)
  return {
    key: `${nodePackId}:${index}`,
    nodePackId,
    versionRange,
    installed,
    enabled: installed,
    satisfied: installed,
  }
}

function readManifestText(source: WorkflowNodePackManifest, ...fieldNames: string[]): string {
  return stringValue(readManifestValue(source, ...fieldNames))
}

function stringValue(value: unknown): string {
  if (value === null || value === undefined || value === '') return '-'
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') return String(value)
  return formatListValue(value)
}

function formatBoolean(value: unknown): string {
  if (value === true) return t('settingsDiagnostics.status.yes')
  if (value === false) return t('settingsDiagnostics.status.no')
  return '-'
}

function formatListValue(value: unknown): string {
  if (value === null || value === undefined || value === '') return '-'
  if (Array.isArray(value)) {
    if (value.length === 0) return '-'
    if (value.every((item) => typeof item === 'string')) return value.join(', ')
    return JSON.stringify(value)
  }
  if (typeof value === 'object') {
    if (Object.keys(value).length === 0) return '-'
    return JSON.stringify(value)
  }
  return String(value)
}
</script>
