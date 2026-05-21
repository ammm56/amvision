<template>
  <section class="page-stack">
    <header class="page-header">
      <div>
        <p class="page-kicker">{{ t('customNodes.kicker') }}</p>
        <h1>{{ t('customNodes.title') }}</h1>
        <p class="page-description">{{ t('customNodes.description') }}</p>
      </div>
      <div class="page-actions">
        <label v-if="activeTab === 'nodes'" class="segmented-field custom-node-catalog__runtime-filter">
          <span>{{ t('customNodes.fields.runtimeKind') }}</span>
          <SelectField :model-value="runtimeKindFilter" :options="runtimeKindOptions" @update:model-value="setRuntimeKindFilter" />
        </label>
        <Button variant="secondary" :disabled="loading" @click="loadCatalog">
          <RefreshCw :size="16" />
          {{ t('common.refresh') }}
        </Button>
      </div>
    </header>

    <InlineError :message="errorMessage" />

    <div class="view-tabs custom-node-catalog__tabs" role="tablist" aria-label="Custom node views">
      <button
        v-for="tab in tabs"
        :key="tab.id"
        class="view-tab"
        :class="{ 'is-active': activeTab === tab.id }"
        type="button"
        role="tab"
        :aria-selected="activeTab === tab.id"
        @click="selectTab(tab.id)"
      >
        <span>{{ tab.label }}</span>
        <strong>{{ tab.count }}</strong>
      </button>
    </div>

    <div class="summary-grid custom-node-catalog__summary">
      <div>
        <span>{{ t('customNodes.fields.nodeDefinitions') }}</span>
        <strong>{{ catalog?.node_definitions.length ?? 0 }}</strong>
      </div>
      <div>
        <span>{{ t('customNodes.fields.customNodes') }}</span>
        <strong>{{ customNodeCount }}</strong>
      </div>
      <div>
        <span>{{ t('customNodes.fields.nodePacks') }}</span>
        <strong>{{ nodePacks.length }}</strong>
      </div>
      <div>
        <span>{{ t('customNodes.fields.payloadTypes') }}</span>
        <strong>{{ catalog?.payload_contracts.length ?? 0 }}</strong>
      </div>
    </div>

    <section v-if="activeTab === 'nodes'" class="catalog-workbench">
      <aside class="catalog-workbench__sidebar" aria-label="Node catalog groups">
        <button
          class="catalog-group-button"
          :class="{ 'is-active': activeScope.kind === 'all' }"
          type="button"
          @click="selectScope({ kind: 'all' })"
        >
          <Blocks :size="16" />
          <span>{{ t('customNodes.groups.allNodes') }}</span>
          <strong>{{ catalog?.node_definitions.length ?? 0 }}</strong>
        </button>
        <button
          class="catalog-group-button"
          :class="{ 'is-active': activeScope.kind === 'custom' }"
          type="button"
          @click="selectScope({ kind: 'custom' })"
        >
          <Puzzle :size="16" />
          <span>{{ t('customNodes.groups.customNodes') }}</span>
          <strong>{{ customNodeCount }}</strong>
        </button>

        <div class="catalog-workbench__group">
          <p>{{ t('customNodes.groups.nodePacks') }}</p>
          <button
            v-for="pack in nodePacks"
            :key="pack.id"
            class="catalog-list-button"
            :class="{ 'is-active': activeScope.kind === 'pack' && activeScope.value === pack.id }"
            type="button"
            @click="selectScope({ kind: 'pack', value: pack.id })"
          >
            <span>{{ pack.displayName }}</span>
            <strong>{{ countByPack(pack.id) }}</strong>
          </button>
        </div>

        <div class="catalog-workbench__group">
          <p>{{ t('customNodes.groups.payloadTypes') }}</p>
          <button
            v-for="payload in payloadTypes"
            :key="payload.payload_type_id"
            class="catalog-list-button"
            :class="{ 'is-active': activeScope.kind === 'payload' && activeScope.value === payload.payload_type_id }"
            type="button"
            @click="selectScope({ kind: 'payload', value: payload.payload_type_id })"
          >
            <span>{{ payload.display_name || payload.payload_type_id }}</span>
            <strong>{{ countByPayload(payload.payload_type_id) }}</strong>
          </button>
        </div>

        <div class="catalog-workbench__group">
          <p>{{ t('customNodes.groups.capabilityTags') }}</p>
          <button
            v-for="tag in capabilityTags"
            :key="tag"
            class="catalog-list-button"
            :class="{ 'is-active': activeScope.kind === 'capability' && activeScope.value === tag }"
            type="button"
            @click="selectScope({ kind: 'capability', value: tag })"
          >
            <span>{{ tag }}</span>
            <strong>{{ countByCapability(tag) }}</strong>
          </button>
        </div>
      </aside>

      <div class="catalog-workbench__main">
        <div class="catalog-toolbar">
          <label class="field catalog-toolbar__search">
            <span>{{ t('customNodes.fields.keyword') }}</span>
            <span class="input-with-icon">
              <Search :size="16" />
              <input v-model="keyword" :placeholder="t('customNodes.searchPlaceholder')" />
            </span>
          </label>
          <StatusBadge tone="neutral">{{ filteredNodes.length }}</StatusBadge>
        </div>

        <section v-if="activeNodePackManifest" class="node-pack-summary">
          <div class="section-heading">
            <div>
              <p class="page-kicker">{{ t('customNodes.detail.nodePackManifest') }}</p>
              <h2>{{ activeNodePackDisplayName }}</h2>
              <p class="node-pack-summary__description">{{ activeNodePackDescription }}</p>
            </div>
            <StatusBadge tone="info">{{ readManifestText(activeNodePackManifest, 'version') }}</StatusBadge>
          </div>
          <dl class="detail-list node-pack-summary__list">
            <div v-for="item in activeNodePackDetails" :key="item.key">
              <dt>{{ item.label }}</dt>
              <dd>{{ item.value }}</dd>
            </div>
          </dl>
          <section class="node-detail-panel__section">
            <h3>{{ t('customNodes.detail.manifestJson') }}</h3>
            <pre class="json-view custom-node-catalog__json node-pack-summary__json">{{ formatJson(activeNodePackManifest) }}</pre>
          </section>
        </section>

        <EmptyState
          v-if="!loading && filteredNodes.length === 0"
          :title="t('customNodes.emptyTitle')"
          :description="t('customNodes.emptyDescription')"
        />

        <div v-else class="custom-node-catalog__layout">
          <div class="resource-table custom-node-catalog__table">
            <table>
              <thead>
                <tr>
                  <th>{{ t('customNodes.columns.node') }}</th>
                  <th>{{ t('customNodes.columns.category') }}</th>
                  <th>{{ t('customNodes.columns.kind') }}</th>
                  <th>{{ t('customNodes.columns.ports') }}</th>
                  <th>{{ t('customNodes.columns.pack') }}</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="node in filteredNodes"
                  :key="node.node_type_id"
                  :class="{ 'is-selected': selectedNode?.node_type_id === node.node_type_id }"
                  @click="selectNode(node)"
                >
                  <td>
                    <strong>{{ node.display_name || node.node_type_id }}</strong>
                    <span>{{ node.node_type_id }}</span>
                  </td>
                  <td>{{ node.category || '-' }}</td>
                  <td>
                    <StatusBadge :tone="node.implementation_kind === 'custom-node' ? 'info' : 'neutral'">
                      {{ node.implementation_kind }}
                    </StatusBadge>
                    <span>{{ node.runtime_kind }}</span>
                  </td>
                  <td>{{ node.input_ports.length }} / {{ node.output_ports.length }}</td>
                  <td>
                    <strong>{{ node.node_pack_id || '-' }}</strong>
                    <span>{{ node.node_pack_version || '-' }}</span>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>

          <aside class="node-detail-panel">
            <template v-if="selectedNode">
              <div class="node-detail-panel__header">
                <div>
                  <p class="page-kicker">{{ t('customNodes.detailKicker') }}</p>
                  <h2>{{ selectedNode.display_name || selectedNode.node_type_id }}</h2>
                  <p>{{ selectedNode.description || t('common.noValue') }}</p>
                </div>
                <StatusBadge :tone="selectedNode.implementation_kind === 'custom-node' ? 'info' : 'neutral'">
                  {{ selectedNode.runtime_kind }}
                </StatusBadge>
              </div>

              <dl class="detail-list">
                <div>
                  <dt>{{ t('customNodes.fields.nodeTypeId') }}</dt>
                  <dd>{{ selectedNode.node_type_id }}</dd>
                </div>
                <div>
                  <dt>{{ t('customNodes.fields.nodePack') }}</dt>
                  <dd>{{ selectedNode.node_pack_id || '-' }} / {{ selectedNode.node_pack_version || '-' }}</dd>
                </div>
                <div>
                  <dt>{{ t('customNodes.fields.capabilityTags') }}</dt>
                  <dd>{{ selectedNode.capability_tags.length ? selectedNode.capability_tags.join(', ') : '-' }}</dd>
                </div>
              </dl>

              <section class="node-detail-panel__section">
                <h3>{{ t('customNodes.detail.inputs') }}</h3>
                <PortList :ports="selectedNode.input_ports" />
              </section>
              <section class="node-detail-panel__section">
                <h3>{{ t('customNodes.detail.outputs') }}</h3>
                <PortList :ports="selectedNode.output_ports" />
              </section>
              <section class="node-detail-panel__section">
                <h3>{{ t('customNodes.detail.parameters') }}</h3>
                <div v-if="parameterFields.length" class="parameter-list">
                  <article v-for="field in parameterFields" :key="field.parameter_name">
                    <strong>{{ field.display_name || field.parameter_name }}</strong>
                    <span>{{ field.parameter_name }} / {{ field.required ? t('customNodes.required') : t('customNodes.optional') }}</span>
                    <small>{{ t('customNodes.fields.defaultValue') }}: {{ formatValue(field.default_value) }}</small>
                  </article>
                </div>
                <pre v-else class="json-view custom-node-catalog__json">{{ formatJson(selectedNode.parameter_schema) }}</pre>
              </section>
              <section class="node-detail-panel__section">
                <h3>{{ t('customNodes.detail.runtimeRequirements') }}</h3>
                <pre class="json-view custom-node-catalog__json">{{ formatJson(selectedNode.runtime_requirements) }}</pre>
              </section>
            </template>
            <EmptyState v-else :title="t('customNodes.noSelectionTitle')" :description="t('customNodes.noSelectionDescription')" />
          </aside>
        </div>
      </div>
    </section>

    <section v-else-if="activeTab === 'packs'" class="node-pack-workbench">
      <div class="resource-table node-pack-workbench__table">
        <table>
          <thead>
            <tr>
              <th>{{ t('customNodes.columns.pack') }}</th>
              <th>{{ t('customNodes.columns.status') }}</th>
              <th>{{ t('customNodes.fields.nodeCount') }}</th>
              <th>{{ t('customNodes.fields.capabilityTags') }}</th>
              <th>{{ t('customNodes.fields.dependencies') }}</th>
              <th>{{ t('customNodes.fields.permissionScopes') }}</th>
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
              <td>{{ pack.capabilitySummary }}</td>
              <td>{{ pack.dependencySummary }}</td>
              <td>{{ pack.permissionScopeSummary }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <aside class="node-detail-panel node-pack-workbench__detail">
        <template v-if="selectedNodePackRow">
          <div class="node-detail-panel__header">
            <div>
              <p class="page-kicker">{{ t('customNodes.detail.nodePackManifest') }}</p>
              <h2>{{ selectedNodePackRow.displayName }}</h2>
              <p>{{ selectedNodePackRow.description }}</p>
            </div>
            <StatusBadge :tone="selectedNodePackRow.statusTone">{{ selectedNodePackRow.statusLabel }}</StatusBadge>
          </div>

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

          <section class="node-detail-panel__section">
            <h3>{{ t('customNodes.detail.manifestJson') }}</h3>
            <pre class="json-view custom-node-catalog__json node-pack-summary__json">{{ formatJson(selectedNodePackRow.manifest) }}</pre>
          </section>
        </template>
        <EmptyState v-else :title="t('customNodes.noSelectionTitle')" :description="t('customNodes.noSelectionDescription')" />
      </aside>
    </section>

    <section v-else class="node-diagnostics-workbench">
      <div class="summary-grid node-diagnostics-workbench__summary">
        <div>
          <span>{{ t('customNodes.diagnostics.loadedPacks') }}</span>
          <strong>{{ nodePackRows.length }}</strong>
        </div>
        <div>
          <span>{{ t('customNodes.diagnostics.warningCount') }}</span>
          <strong>{{ warningPackCount }}</strong>
        </div>
        <div>
          <span>{{ t('customNodes.diagnostics.missingDependencyCount') }}</span>
          <strong>{{ missingDependencyCount }}</strong>
        </div>
        <div>
          <span>{{ t('customNodes.diagnostics.issueCount') }}</span>
          <strong>{{ diagnosticIssues.length }}</strong>
        </div>
      </div>

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
import { Blocks, CircleCheck, Power, PowerOff, Puzzle, RefreshCw, ScrollText, Search } from '@lucide/vue'
import { useI18n } from 'vue-i18n'

import { getWorkflowNodeCatalog } from '@/workflows/workflow-editor/services/node-catalog.service'
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
  WorkflowPayloadContract,
} from '@/workflows/workflow-editor/types'
import Button from '@/shared/ui/components/Button.vue'
import SelectField from '@/shared/ui/components/Select.vue'
import StatusBadge from '@/shared/ui/data-display/StatusBadge.vue'
import EmptyState from '@/shared/ui/feedback/EmptyState.vue'
import InlineError from '@/shared/ui/feedback/InlineError.vue'

type SelectValue = string | number | boolean | null
type CatalogTabId = 'nodes' | 'packs' | 'diagnostics'
type BadgeTone = 'neutral' | 'success' | 'warning' | 'danger' | 'info'

type CatalogScope =
  | { kind: 'all' }
  | { kind: 'custom' }
  | { kind: 'pack'; value: string }
  | { kind: 'payload'; value: string }
  | { kind: 'capability'; value: string }

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
    const { t } = useI18n()
    return () =>
      props.ports.length === 0
        ? h('p', { class: 'result-note' }, '-')
        : h(
            'div',
            { class: 'port-list' },
            props.ports.map((port) =>
              h('article', { key: port.name }, [
                h('strong', port.display_name || port.name),
                h('span', `${port.name} / ${port.payload_type_id}`),
                h('small', port.required ? t('customNodes.required') : t('customNodes.optional')),
              ]),
            ),
          )
  },
})

const { t } = useI18n()
const catalog = ref<WorkflowNodeCatalogResponse | null>(null)
const nodePackStatus = ref<NodePackStatusResponse | null>(null)
const loading = ref(false)
const actionKey = ref<string | null>(null)
const errorMessage = ref<string | null>(null)
const keyword = ref('')
const runtimeKindFilter = ref('all')
const activeTab = ref<CatalogTabId>('nodes')
const activeScope = ref<CatalogScope>({ kind: 'all' })
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
const customNodeCount = computed(() => allNodes.value.filter((node) => node.implementation_kind === 'custom-node').length)
const payloadTypes = computed<WorkflowPayloadContract[]>(() => catalog.value?.payload_contracts ?? [])
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
const nodePackRows = computed<NodePackStatusRow[]>(() =>
  nodePacks.value.map((pack) => buildNodePackStatusRow(pack)).sort((left, right) => left.displayName.localeCompare(right.displayName)),
)
const warningPackCount = computed(() => nodePackRows.value.filter((pack) => pack.statusTone === 'warning' || pack.statusTone === 'danger').length)
const missingDependencyCount = computed(() => nodePackRows.value.reduce((count, pack) => count + pack.dependencies.filter((item) => !item.satisfied).length, 0))
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
    if (!matchesScope(node, activeScope.value)) return false
    if (!normalizedKeyword) return true
    return [
      node.node_type_id,
      node.display_name,
      node.category,
      node.description,
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
const activeNodePackManifest = computed(() => {
  if (activeScope.value.kind !== 'pack') return null
  return findNodePackManifest(activeScope.value.value)
})
const activeNodePackDisplayName = computed(() => {
  const manifest = activeNodePackManifest.value
  return manifest ? readManifestText(manifest, 'display_name', 'displayName', 'name', 'id') : '-'
})
const activeNodePackDescription = computed(() => {
  const manifest = activeNodePackManifest.value
  return manifest ? readManifestText(manifest, 'description') : '-'
})
const activeNodePackDetails = computed<NodePackDetailItem[]>(() => {
  const manifest = activeNodePackManifest.value
  if (!manifest || activeScope.value.kind !== 'pack') return []
  return [
    { key: 'id', label: t('customNodes.fields.nodePackId'), value: activeScope.value.value },
    { key: 'version', label: t('customNodes.fields.version'), value: readManifestText(manifest, 'version') },
    { key: 'category', label: t('customNodes.fields.category'), value: readManifestText(manifest, 'category') },
    { key: 'enabled', label: t('customNodes.fields.enabledByDefault'), value: formatBoolean(readManifestValue(manifest, 'enabledByDefault', 'enabled_by_default')) },
    { key: 'node-count', label: t('customNodes.fields.nodeCount'), value: String(countByPack(activeScope.value.value)) },
    { key: 'capabilities', label: t('customNodes.fields.capabilityTags'), value: formatListValue(readManifestValue(manifest, 'capabilities')) },
    { key: 'dependencies', label: t('customNodes.fields.dependencies'), value: formatListValue(readManifestValue(manifest, 'dependencies')) },
    { key: 'permissions', label: t('customNodes.fields.permissionScopes'), value: formatListValue(readManifestValue(manifest, 'permissionScopes', 'permission_scopes')) },
    { key: 'entrypoints', label: t('customNodes.fields.entrypoints'), value: formatListValue(readManifestValue(manifest, 'entrypoints')) },
    { key: 'catalog-path', label: t('customNodes.fields.catalogPath'), value: readManifestText(manifest, 'customNodeCatalogPath', 'custom_node_catalog_path') },
  ]
})
const selectedNodePackRow = computed(() => {
  if (!selectedNodePackId.value) return nodePackRows.value[0] ?? null
  return nodePackRows.value.find((pack) => pack.id === selectedNodePackId.value) ?? nodePackRows.value[0] ?? null
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
  if (!selectedNode.value || !nodes.some((node) => node.node_type_id === selectedNode.value?.node_type_id)) {
    selectedNode.value = nodes[0] ?? null
  }
})

watch(runtimeKindOptions, (options) => {
  if (!options.some((option) => option.value === runtimeKindFilter.value)) {
    runtimeKindFilter.value = 'all'
  }
})

watch(nodePackRows, (rows) => {
  if (!selectedNodePackId.value || !rows.some((pack) => pack.id === selectedNodePackId.value)) {
    selectedNodePackId.value = rows[0]?.id ?? null
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
    selectedNode.value = filteredNodes.value[0] ?? null
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
    selectedNode.value = filteredNodes.value[0] ?? null
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : t('customNodes.messages.actionFailed')
  } finally {
    actionKey.value = null
  }
}

function selectScope(scope: CatalogScope): void {
  activeScope.value = scope
  if (scope.kind === 'pack') selectedNodePackId.value = scope.value
}

function selectNode(node: NodeDefinition): void {
  selectedNode.value = node
}

function selectTab(tabId: CatalogTabId): void {
  activeTab.value = tabId
}

function selectNodePack(packId: string): void {
  selectedNodePackId.value = packId
}

function setRuntimeKindFilter(value: SelectValue): void {
  runtimeKindFilter.value = typeof value === 'string' ? value : 'all'
}

function matchesScope(node: NodeDefinition, scope: CatalogScope): boolean {
  if (scope.kind === 'all') return true
  if (scope.kind === 'custom') return node.implementation_kind === 'custom-node'
  if (scope.kind === 'pack') return node.node_pack_id === scope.value
  if (scope.kind === 'payload') {
    return [...node.input_ports, ...node.output_ports].some((port) => port.payload_type_id === scope.value)
  }
  return node.capability_tags.includes(scope.value)
}

function countByPack(packId: string): number {
  return allNodes.value.filter((node) => node.node_pack_id === packId).length
}

function countByPayload(payloadTypeId: string): number {
  return allNodes.value.filter((node) =>
    [...node.input_ports, ...node.output_ports].some((port) => port.payload_type_id === payloadTypeId),
  ).length
}

function countByCapability(tag: string): number {
  return allNodes.value.filter((node) => node.capability_tags.includes(tag)).length
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