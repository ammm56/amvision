<template>
  <div
    v-if="open"
    class="workflow-node-picker"
    :class="`workflow-node-picker--${mode}`"
    :style="pickerStyle"
    role="dialog"
    :aria-label="displayTitle"
    @mousedown.stop
    @click.stop
    @keydown.esc.stop.prevent="emit('close')"
    @contextmenu.prevent.stop
  >
    <header class="workflow-node-picker__header">
      <h2>{{ connectionLabel }}</h2>
      <button type="button" class="workflow-node-picker__close" :title="t('workflowEditor.nodePicker.close')" :aria-label="t('workflowEditor.nodePicker.close')" @click="emit('close')">
        <X :size="15" />
      </button>
    </header>

    <label class="workflow-node-picker__search">
      <Search :size="15" />
      <input
        ref="searchInputRef"
        v-model="searchQuery"
        :placeholder="t('workflowEditor.nodePicker.searchPlaceholder')"
        @keydown.enter.prevent="selectFirstVisibleNode"
        @keydown.esc.stop.prevent="emit('close')"
      />
    </label>

    <div class="workflow-node-picker__body" :class="{ 'is-searching': Boolean(searchQuery) }">
      <nav class="workflow-node-picker__sources" :aria-label="t('workflowEditor.nodePicker.sourceAria')">
        <button
          v-for="source in sourceGroups"
          :key="source.id"
          type="button"
          :class="{ 'is-active': source.id === activeSourceId }"
          @click="selectSource(source.id)"
        >
          <span>
            <strong>{{ source.label }}</strong>
          </span>
          <em>{{ source.count }}</em>
          <ChevronRight :size="14" />
        </button>
      </nav>

      <nav v-if="!searchQuery" class="workflow-node-picker__categories" :aria-label="t('workflowEditor.nodePicker.categoryAria')">
        <template v-for="row in categoryRows" :key="row.id">
          <div v-if="row.kind === 'root'" class="workflow-node-picker__category-root">
            <span>{{ row.label }}</span>
            <em>{{ row.count }}</em>
          </div>
          <button
            v-else
            type="button"
            class="is-child"
            :class="{ 'is-active': row.id === activeCategoryId }"
            @click="activeCategoryId = row.id"
          >
            <span>{{ row.label }}</span>
            <em>{{ row.definitions.length }}</em>
          </button>
        </template>
      </nav>

      <section class="workflow-node-picker__nodes" :aria-label="t('workflowEditor.nodePicker.resultAria')">
        <button
          v-for="definition in visibleNodes"
          :key="definition.node_type_id"
          type="button"
          class="workflow-node-picker__node"
          @click="emit('select', definition)"
        >
          <strong>{{ readDefinitionDisplayName(definition) }}</strong>
          <span>{{ readNodeCategoryLabel(definition.category) }}</span>
          <p v-if="readDefinitionDescription(definition)">{{ readDefinitionDescription(definition) }}</p>
          <small>{{ definition.node_type_id }}</small>
        </button>
        <div v-if="visibleNodes.length === 0" class="workflow-node-picker__empty">
          {{ t('workflowEditor.nodePicker.empty') }}
        </div>
      </section>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ChevronRight, Search, X } from '@lucide/vue'
import { computed, nextTick, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import type { SupportedLocale } from '@/platform/i18n'

import {
  resolveNodeDefinitionDescription,
  resolveNodeDefinitionDisplayName,
} from '../node-definition-localization'
import {
  compareNodeCategories,
  humanizeNodeCategoryToken,
  readNodeCategoryLabel,
  readNodeCategoryParts,
} from '../node-taxonomy'
import type { NodeDefinition } from '../types'

type NodePickerMode = 'context-menu' | 'link-drop'
type RequiredPortDirection = 'input' | 'output'

interface SourceGroup {
  id: string
  label: string
  description: string
  count: number
  definitions: NodeDefinition[]
}

interface CategoryGroup {
  id: string
  label: string
  definitions: NodeDefinition[]
}

type CategoryRow =
  | { id: string; kind: 'root'; label: string; count: number }
  | { id: string; kind: 'category'; label: string; definitions: NodeDefinition[] }

const props = withDefaults(defineProps<{
  open: boolean
  x: number
  y: number
  definitions: NodeDefinition[]
  mode?: NodePickerMode
  title?: string
  requiredPortDirection?: RequiredPortDirection | null
  requiredPayloadTypeId?: string | null
}>(), {
  mode: 'context-menu',
  requiredPortDirection: null,
  requiredPayloadTypeId: null,
})

const emit = defineEmits<{
  select: [definition: NodeDefinition]
  close: []
}>()

const searchInputRef = ref<HTMLInputElement | null>(null)
const searchQuery = ref('')
const activeSourceId = ref('')
const activeCategoryId = ref('')
const { t, locale } = useI18n()
const currentLocale = computed(() => (typeof locale.value === 'string' ? locale.value : 'en-US') as SupportedLocale)
const nodePickerWidth = 860
const nodePickerHeight = 560

const pickerStyle = computed(() => ({
  left: `${clampToViewport(props.x, nodePickerWidth, 'width')}px`,
  top: `${clampToViewport(props.y, nodePickerHeight, 'height')}px`,
}))

const displayTitle = computed(() => props.title ?? t('workflowEditor.nodePicker.addNode'))

const connectionLabel = computed(() => {
  if (!props.requiredPortDirection) return t('workflowEditor.nodePicker.catalogTitle')
  const directionText = props.requiredPortDirection === 'input'
    ? t('workflowEditor.nodePicker.requiresInputPort')
    : t('workflowEditor.nodePicker.requiresOutputPort')
  return props.requiredPayloadTypeId ? `${directionText} / ${props.requiredPayloadTypeId}` : directionText
})

const compatibleDefinitions = computed(() => props.definitions.filter(
  (definition) => definition.metadata.catalogHidden !== true && matchesConnectionFilter(definition),
))

const sourceGroups = computed<SourceGroup[]>(() => {
  const coreDefinitions = compatibleDefinitions.value.filter((definition) => definition.implementation_kind === 'core-node')
  const customDefinitions = compatibleDefinitions.value.filter((definition) => definition.implementation_kind === 'custom-node')
  const groups: SourceGroup[] = []
  if (coreDefinitions.length > 0) {
    groups.push({
      id: 'core',
      label: t('workflowEditor.palette.coreNodes'),
      description: t('workflowEditor.nodePicker.coreSourceDescription'),
      count: coreDefinitions.length,
      definitions: sortDefinitions(coreDefinitions),
    })
  }
  const customByPack = new Map<string, NodeDefinition[]>()
  for (const definition of customDefinitions) {
    const packId = definition.node_pack_id || 'custom-node-pack'
    const items = customByPack.get(packId) ?? []
    items.push(definition)
    customByPack.set(packId, items)
  }
  for (const [packId, definitions] of [...customByPack.entries()].sort(([left], [right]) => left.localeCompare(right))) {
    groups.push({
      id: `custom:${packId}`,
      label: formatNodePackLabel(packId),
      description: t('workflowEditor.nodePicker.customSourceDescription'),
      count: definitions.length,
      definitions: sortDefinitions(definitions),
    })
  }
  return groups
})

const selectedSource = computed(() => sourceGroups.value.find((source) => source.id === activeSourceId.value) ?? sourceGroups.value[0] ?? null)

const categoryGroups = computed<CategoryGroup[]>(() => {
  const groupsByCategory = new Map<string, NodeDefinition[]>()
  for (const definition of selectedSource.value?.definitions ?? []) {
    const items = groupsByCategory.get(definition.category) ?? []
    items.push(definition)
    groupsByCategory.set(definition.category, items)
  }
  return [...groupsByCategory.entries()]
    .sort(([left], [right]) => compareNodeCategories(selectedSource.value?.id ?? '', left, right))
    .map(([category, definitions]) => ({
      id: category,
      label: readNodeCategoryLabel(category),
      definitions: sortDefinitions(definitions),
    }))
})

const categoryRows = computed<CategoryRow[]>(() => {
  const groupsByRoot = new Map<string, { label: string; categories: CategoryGroup[] }>()
  for (const category of categoryGroups.value) {
    const parts = readNodeCategoryParts(category.id)
    const group = groupsByRoot.get(parts.rootId) ?? {
      label: parts.rootLabel,
      categories: [],
    }
    group.categories.push({
      ...category,
      label: parts.childLabel,
    })
    groupsByRoot.set(parts.rootId, group)
  }

  const rows: CategoryRow[] = []
  for (const [rootId, group] of groupsByRoot) {
    rows.push({
      id: `root:${rootId}`,
      kind: 'root',
      label: group.label,
      count: group.categories.reduce((count, category) => count + category.definitions.length, 0),
    })
    for (const category of group.categories) {
      rows.push({
        id: category.id,
        kind: 'category',
        label: category.label,
        definitions: category.definitions,
      })
    }
  }
  return rows
})

const selectedCategory = computed(() => categoryGroups.value.find((category) => category.id === activeCategoryId.value) ?? categoryGroups.value[0] ?? null)

const visibleNodes = computed(() => {
  const query = searchQuery.value.trim().toLowerCase()
  const baseDefinitions = query ? (selectedSource.value?.definitions ?? []) : (selectedCategory.value?.definitions ?? [])
  if (!query) return baseDefinitions
  return baseDefinitions.filter((definition) => buildSearchText(definition).includes(query)).slice(0, 80)
})

watch(sourceGroups, (groups) => {
  if (!groups.some((group) => group.id === activeSourceId.value)) {
    activeSourceId.value = groups[0]?.id ?? ''
  }
}, { immediate: true })

watch(categoryGroups, (groups) => {
  if (!groups.some((group) => group.id === activeCategoryId.value)) {
    activeCategoryId.value = groups[0]?.id ?? ''
  }
}, { immediate: true })

watch(() => props.open, (open) => {
  if (!open) {
    searchQuery.value = ''
    return
  }
  nextTick(() => searchInputRef.value?.focus())
})

function selectSource(sourceId: string): void {
  activeSourceId.value = sourceId
  activeCategoryId.value = ''
  searchQuery.value = ''
  nextTick(() => searchInputRef.value?.focus())
}

function selectFirstVisibleNode(): void {
  const definition = visibleNodes.value[0]
  if (definition) emit('select', definition)
}

function matchesConnectionFilter(definition: NodeDefinition): boolean {
  const requiredDirection = props.requiredPortDirection
  if (!requiredDirection) return true
  const ports = requiredDirection === 'input' ? definition.input_ports : definition.output_ports
  if (ports.length === 0) return false
  const requiredPayloadTypeId = props.requiredPayloadTypeId?.trim()
  if (!requiredPayloadTypeId) return true
  return ports.some((port) => !port.payload_type_id || port.payload_type_id === requiredPayloadTypeId)
}

function sortDefinitions(definitions: NodeDefinition[]): NodeDefinition[] {
  return [...definitions].sort((left, right) => readDefinitionDisplayName(left).localeCompare(readDefinitionDisplayName(right)))
}

function buildSearchText(definition: NodeDefinition): string {
  return [
    readDefinitionDisplayName(definition),
    definition.node_type_id,
    definition.category,
    readDefinitionDescription(definition),
    definition.node_pack_id ?? '',
    ...definition.capability_tags,
  ].join(' ').toLowerCase()
}

function readDefinitionDisplayName(definition: NodeDefinition): string {
  return resolveNodeDefinitionDisplayName(definition, currentLocale.value)
}

function readDefinitionDescription(definition: NodeDefinition): string {
  return resolveNodeDefinitionDescription(definition, currentLocale.value)
}

function formatNodePackLabel(packId: string): string {
  const tokens = packId
    .split(/[._-]+/)
    .filter((token) => token && token.toLowerCase() !== 'nodes')
  return tokens.map(humanizeNodeCategoryToken).join(' ')
}

function clampToViewport(value: number, size: number, axis: 'width' | 'height'): number {
  if (typeof window === 'undefined') return value
  const viewportSize = axis === 'width' ? window.innerWidth : window.innerHeight
  return Math.max(12, Math.min(value, viewportSize - size - 12))
}
</script>
