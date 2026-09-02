<template>
  <button
    type="button"
    class="workflow-color-map-summary"
    :disabled="disabled"
    :aria-label="t('workflowEditor.colorMap.editAria', { label })"
    data-color-map-open
    @click="openEditor"
  >
    <span v-if="summaryColors.length" class="workflow-color-map-summary__swatches" aria-hidden="true">
      <span
        v-for="(color, index) in summaryColors"
        :key="`${color}-${index}`"
        class="workflow-color-map-summary__swatch"
        :style="readSwatchStyle(color)"
      />
    </span>
    <span v-else class="workflow-color-map-summary__automatic" aria-hidden="true">
      <Palette :size="14" />
    </span>
    <span class="workflow-color-map-summary__text">
      {{ configuredCount
        ? t('workflowEditor.colorMap.configuredCount', { count: configuredCount })
        : t('workflowEditor.colorMap.automatic') }}
    </span>
    <span class="workflow-color-map-summary__edit">{{ t('workflowEditor.colorMap.edit') }}</span>
  </button>

  <Teleport to="body">
    <ConfirmDialog
      v-if="editorOpen"
      :title="label"
      :confirm-label="t('workflowEditor.colorMap.apply')"
      :cancel-label="t('common.cancel')"
      confirm-variant="primary"
      @cancel="closeEditor"
      @confirm="applyEditor"
    >
      <div class="workflow-color-map-editor">
        <div class="workflow-color-map-editor__toolbar">
          <Button
            size="sm"
            :variant="advancedMode ? 'secondary' : 'ghost'"
            data-color-map-advanced
            @click="toggleAdvancedMode"
          >
            <Braces :size="14" aria-hidden="true" />
            {{ advancedMode ? t('workflowEditor.colorMap.formEditor') : t('workflowEditor.colorMap.jsonEditor') }}
          </Button>
        </div>

        <template v-if="!advancedMode">
          <div class="workflow-color-map-editor__header" aria-hidden="true">
            <span>{{ keyLabel }}</span>
            <span>{{ valueLabel }}</span>
          </div>

          <div v-if="draftEntries.length" class="workflow-color-map-editor__rows">
            <div v-for="entry in draftEntries" :key="entry.id" class="workflow-color-map-editor__row">
              <input
                v-model="entry.name"
                class="workflow-color-map-editor__name"
                :aria-label="keyLabel"
                :placeholder="t('workflowEditor.colorMap.classNamePlaceholder')"
                data-color-map-name
              >
              <div class="workflow-color-map-editor__color">
                <button
                  type="button"
                  class="workflow-color-map-editor__swatch-button"
                  :aria-label="t('workflowEditor.colorMap.chooseColor', { name: entry.name || keyLabel })"
                  :style="readSwatchStyle(entry.color)"
                  data-color-map-swatch
                  @click="togglePalette(entry.id)"
                />
                <input
                  v-model="entry.color"
                  class="workflow-color-map-editor__hex"
                  :class="{ 'is-invalid': Boolean(entry.color) && !isHexColor(entry.color) }"
                  :aria-label="valueLabel"
                  placeholder="#RRGGBB"
                  spellcheck="false"
                  data-color-map-hex
                  @blur="normalizeEntryColor(entry)"
                >
                <button
                  type="button"
                  class="workflow-color-map-editor__delete"
                  :aria-label="t('workflowEditor.colorMap.deleteEntry', { name: entry.name || keyLabel })"
                  data-color-map-delete
                  @click="removeEntry(entry.id)"
                >
                  <Trash2 :size="15" aria-hidden="true" />
                </button>
              </div>
              <div
                v-if="activePaletteEntryId === entry.id"
                class="workflow-color-map-palette"
                :aria-label="t('workflowEditor.colorMap.palette')"
              >
                <button
                  v-for="color in paletteColors"
                  :key="color"
                  type="button"
                  class="workflow-color-map-palette__color"
                  :class="{ 'is-selected': normalizeHexColor(entry.color) === color }"
                  :style="{ backgroundColor: color }"
                  :aria-label="color"
                  :title="color"
                  @click="selectPaletteColor(entry, color)"
                />
              </div>
            </div>
          </div>

          <div v-else class="workflow-color-map-editor__empty">
            {{ t('workflowEditor.colorMap.empty') }}
          </div>

          <Button size="sm" variant="secondary" data-color-map-add @click="addEntry">
            <Plus :size="14" aria-hidden="true" />
            {{ t('workflowEditor.colorMap.add') }}
          </Button>
        </template>

        <label v-else class="workflow-color-map-editor__json">
          <span>{{ t('workflowEditor.colorMap.jsonLabel') }}</span>
          <textarea
            v-model="jsonDraft"
            spellcheck="false"
            data-color-map-json
          />
        </label>

        <p v-if="validationError" class="workflow-color-map-editor__error" role="alert">
          {{ validationError }}
        </p>
      </div>
    </ConfirmDialog>
  </Teleport>
</template>

<script setup lang="ts">
import { Braces, Palette, Plus, Trash2 } from '@lucide/vue'
import { computed, ref } from 'vue'

import { useTranslation } from '@/platform/i18n'
import Button from '@/shared/ui/components/Button.vue'
import ConfirmDialog from '@/shared/ui/components/ConfirmDialog.vue'

interface ColorMapEntry {
  id: number
  name: string
  color: string
}

const props = withDefaults(
  defineProps<{
    modelValue: unknown
    label: string
    keyLabel?: string
    valueLabel?: string
    disabled?: boolean
  }>(),
  {
    keyLabel: 'Key',
    valueLabel: 'Color',
    disabled: false,
  },
)

const emit = defineEmits<{
  'update:modelValue': [value: Record<string, string>]
}>()

const { t } = useTranslation()
const hexColorPattern = /^#[0-9A-Fa-f]{6}$/
const paletteColors = [
  '#00C853', '#00B8D4', '#2962FF', '#6200EA',
  '#AA00FF', '#D500F9', '#D50000', '#FF6D00',
  '#FFB300', '#FFD600', '#64DD17', '#1DE9B6',
  '#607D8B', '#546E7A', '#37474F', '#FFFFFF',
]

const editorOpen = ref(false)
const advancedMode = ref(false)
const draftEntries = ref<ColorMapEntry[]>([])
const jsonDraft = ref('')
const validationError = ref('')
const activePaletteEntryId = ref<number | null>(null)
let nextEntryId = 1

const modelEntries = computed(() => readColorMapEntries(props.modelValue))
const configuredCount = computed(() => modelEntries.value.length)
const summaryColors = computed(() => modelEntries.value.slice(0, 5).map((entry) => entry.color))

function openEditor(): void {
  if (props.disabled) return
  draftEntries.value = cloneEntries(modelEntries.value)
  jsonDraft.value = formatColorMapJson(entriesToObject(draftEntries.value))
  validationError.value = ''
  advancedMode.value = false
  activePaletteEntryId.value = null
  editorOpen.value = true
}

function closeEditor(): void {
  editorOpen.value = false
  activePaletteEntryId.value = null
  validationError.value = ''
}

function applyEditor(): void {
  const value = advancedMode.value ? parseJsonDraft() : validateEntries(draftEntries.value)
  if (!value) return
  emit('update:modelValue', value)
  closeEditor()
}

function toggleAdvancedMode(): void {
  validationError.value = ''
  activePaletteEntryId.value = null
  if (advancedMode.value) {
    const parsed = parseJsonDraft()
    if (!parsed) return
    draftEntries.value = cloneEntries(readColorMapEntries(parsed))
    advancedMode.value = false
    return
  }
  const value = validateEntries(draftEntries.value)
  if (!value) return
  jsonDraft.value = formatColorMapJson(value)
  advancedMode.value = true
}

function addEntry(): void {
  validationError.value = ''
  const color = paletteColors[draftEntries.value.length % paletteColors.length] ?? '#00C853'
  draftEntries.value.push({ id: nextEntryId++, name: '', color })
}

function removeEntry(entryId: number): void {
  draftEntries.value = draftEntries.value.filter((entry) => entry.id !== entryId)
  if (activePaletteEntryId.value === entryId) activePaletteEntryId.value = null
  validationError.value = ''
}

function togglePalette(entryId: number): void {
  activePaletteEntryId.value = activePaletteEntryId.value === entryId ? null : entryId
}

function selectPaletteColor(entry: ColorMapEntry, color: string): void {
  entry.color = color
  activePaletteEntryId.value = null
  validationError.value = ''
}

function normalizeEntryColor(entry: ColorMapEntry): void {
  if (isHexColor(entry.color)) entry.color = normalizeHexColor(entry.color)
}

function validateEntries(entries: ColorMapEntry[]): Record<string, string> | null {
  const result: Record<string, string> = {}
  const names = new Set<string>()
  for (const entry of entries) {
    const name = entry.name.trim()
    if (!name) {
      validationError.value = t('workflowEditor.colorMap.nameRequired')
      return null
    }
    if (names.has(name)) {
      validationError.value = t('workflowEditor.colorMap.duplicateName', { name })
      return null
    }
    if (!isHexColor(entry.color)) {
      validationError.value = t('workflowEditor.colorMap.invalidColor', { name })
      return null
    }
    names.add(name)
    result[name] = normalizeHexColor(entry.color)
  }
  validationError.value = ''
  return result
}

function parseJsonDraft(): Record<string, string> | null {
  try {
    const duplicateName = findDuplicateTopLevelJsonKey(jsonDraft.value)
    if (duplicateName) {
      validationError.value = t('workflowEditor.colorMap.duplicateName', { name: duplicateName })
      return null
    }
    const parsed: unknown = JSON.parse(jsonDraft.value)
    if (!isPlainObject(parsed)) {
      validationError.value = t('workflowEditor.colorMap.objectRequired')
      return null
    }
    const entries = readColorMapEntries(parsed)
    if (entries.length !== Object.keys(parsed).length) {
      validationError.value = t('workflowEditor.colorMap.stringValuesRequired')
      return null
    }
    return validateEntries(entries)
  } catch (error) {
    const detail = error instanceof Error && error.message ? `: ${error.message}` : ''
    validationError.value = `${t('workflowEditor.colorMap.invalidJson')}${detail}`
    return null
  }
}

function readColorMapEntries(value: unknown): ColorMapEntry[] {
  if (!isPlainObject(value)) return []
  return Object.entries(value).flatMap(([name, color]) => (
    typeof color === 'string' ? [{ id: nextEntryId++, name, color }] : []
  ))
}

function cloneEntries(entries: ColorMapEntry[]): ColorMapEntry[] {
  return entries.map((entry) => ({ ...entry, id: nextEntryId++ }))
}

function entriesToObject(entries: ColorMapEntry[]): Record<string, string> {
  return Object.fromEntries(entries.map((entry) => [entry.name, entry.color]))
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === 'object' && !Array.isArray(value))
}

function isHexColor(value: string): boolean {
  return hexColorPattern.test(value.trim())
}

function normalizeHexColor(value: string): string {
  return value.trim().toUpperCase()
}

function readSwatchStyle(color: string): Record<string, string> {
  return { backgroundColor: isHexColor(color) ? normalizeHexColor(color) : 'transparent' }
}

function formatColorMapJson(value: Record<string, string>): string {
  return JSON.stringify(value, null, 2)
}

function findDuplicateTopLevelJsonKey(source: string): string | null {
  let index = skipWhitespace(source, 0)
  if (source[index] !== '{') return null
  index = skipWhitespace(source, index + 1)
  const keys = new Set<string>()
  while (index < source.length && source[index] !== '}') {
    const keyToken = readJsonStringToken(source, index)
    if (!keyToken) return null
    const key = JSON.parse(keyToken.token) as string
    if (keys.has(key)) return key
    keys.add(key)
    index = skipWhitespace(source, keyToken.nextIndex)
    if (source[index] !== ':') return null
    index = skipJsonValue(source, skipWhitespace(source, index + 1))
    index = skipWhitespace(source, index)
    if (source[index] === ',') {
      index = skipWhitespace(source, index + 1)
      continue
    }
    break
  }
  return null
}

function readJsonStringToken(source: string, startIndex: number): { token: string; nextIndex: number } | null {
  if (source[startIndex] !== '"') return null
  let escaped = false
  for (let index = startIndex + 1; index < source.length; index += 1) {
    const character = source[index]
    if (!escaped && character === '"') {
      return { token: source.slice(startIndex, index + 1), nextIndex: index + 1 }
    }
    if (!escaped && character === '\\') {
      escaped = true
    } else {
      escaped = false
    }
  }
  return null
}

function skipJsonValue(source: string, startIndex: number): number {
  let index = startIndex
  let depth = 0
  let inString = false
  let escaped = false
  while (index < source.length) {
    const character = source[index]
    if (inString) {
      if (!escaped && character === '"') inString = false
      if (!escaped && character === '\\') escaped = true
      else escaped = false
      index += 1
      continue
    }
    if (character === '"') inString = true
    else if (character === '{' || character === '[') depth += 1
    else if (character === '}' || character === ']') {
      if (depth === 0) return index
      depth -= 1
    } else if (character === ',' && depth === 0) return index
    index += 1
  }
  return index
}

function skipWhitespace(source: string, startIndex: number): number {
  let index = startIndex
  while (index < source.length && /\s/.test(source[index] ?? '')) index += 1
  return index
}
</script>

<style scoped>
.workflow-color-map-summary {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: 6px;
  width: 100%;
  min-width: 0;
  min-height: 28px;
  padding: 3px 7px;
  border: 1px solid var(--graph-line, #4a5458);
  border-radius: 7px;
  color: var(--graph-text, #e7ecef);
  background: var(--graph-panel-soft, #24292d);
  cursor: pointer;
}

.workflow-color-map-summary:focus-visible {
  border-color: var(--am-action-primary);
  outline: none;
  box-shadow: inset 0 0 0 1px var(--am-action-primary);
}

.workflow-color-map-summary:disabled {
  cursor: not-allowed;
  opacity: 0.62;
}

.workflow-color-map-summary__swatches {
  display: inline-flex;
  min-width: 16px;
}

.workflow-color-map-summary__swatch {
  width: 14px;
  height: 14px;
  margin-left: -4px;
  border: 1px solid color-mix(in srgb, var(--graph-text, #e7ecef) 58%, transparent);
  border-radius: 50%;
  box-shadow: 0 0 0 1px var(--graph-panel-soft, #24292d);
}

.workflow-color-map-summary__swatch:first-child {
  margin-left: 0;
}

.workflow-color-map-summary__automatic {
  display: inline-flex;
  color: var(--graph-muted, #a9b5ad);
}

.workflow-color-map-summary__text {
  min-width: 0;
  overflow: hidden;
  text-align: left;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.workflow-color-map-summary__edit {
  color: var(--graph-muted, #a9b5ad);
  font-size: 11px;
}

.workflow-color-map-editor {
  display: grid;
  gap: 12px;
  min-width: 0;
}

.workflow-color-map-editor__toolbar {
  display: flex;
  justify-content: flex-end;
}

.workflow-color-map-editor__toolbar :deep(.ui-button),
.workflow-color-map-editor > :deep(.ui-button) {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  justify-self: start;
}

.workflow-color-map-editor__header,
.workflow-color-map-editor__row {
  display: grid;
  grid-template-columns: minmax(150px, 1fr) minmax(190px, 0.9fr);
  gap: 10px;
}

.workflow-color-map-editor__header {
  color: var(--am-text-subtle);
  font-size: 12px;
  font-weight: 700;
}

.workflow-color-map-editor__rows {
  display: grid;
  gap: 8px;
  max-height: min(42vh, 360px);
  padding-right: 3px;
  overflow-y: auto;
}

.workflow-color-map-editor__row {
  position: relative;
  align-items: center;
}

.workflow-color-map-editor__name,
.workflow-color-map-editor__hex,
.workflow-color-map-editor__json textarea {
  width: 100%;
  min-width: 0;
  border: 1px solid var(--am-border-strong);
  border-radius: var(--am-radius-sm);
  color: var(--am-text);
  background: var(--am-surface);
}

.workflow-color-map-editor__name,
.workflow-color-map-editor__hex {
  height: 34px;
  padding: 0 9px;
}

.workflow-color-map-editor__hex {
  font-family: Consolas, 'Courier New', monospace;
}

.workflow-color-map-editor__hex.is-invalid {
  border-color: var(--am-danger);
}

.workflow-color-map-editor__color {
  display: grid;
  grid-template-columns: 34px minmax(92px, 1fr) 34px;
  gap: 6px;
}

.workflow-color-map-editor__swatch-button,
.workflow-color-map-editor__delete {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 34px;
  height: 34px;
  border: 1px solid var(--am-border-strong);
  border-radius: var(--am-radius-sm);
  cursor: pointer;
}

.workflow-color-map-editor__swatch-button {
  box-shadow: inset 0 0 0 4px var(--am-surface);
}

.workflow-color-map-editor__delete {
  color: var(--am-text-subtle);
  background: var(--am-surface);
}

.workflow-color-map-editor__delete:hover {
  border-color: var(--am-danger);
  color: var(--am-danger);
}

.workflow-color-map-palette {
  grid-column: 2;
  display: grid;
  grid-template-columns: repeat(8, 24px);
  gap: 6px;
  justify-content: end;
  padding: 9px;
  border: 1px solid var(--am-border);
  border-radius: var(--am-radius-sm);
  background: var(--am-surface-raised);
  box-shadow: var(--am-shadow-modal);
}

.workflow-color-map-palette__color {
  width: 24px;
  height: 24px;
  border: 1px solid color-mix(in srgb, var(--am-text) 30%, transparent);
  border-radius: 6px;
  cursor: pointer;
}

.workflow-color-map-palette__color.is-selected {
  outline: 2px solid var(--am-action-primary);
  outline-offset: 2px;
}

.workflow-color-map-editor__empty {
  padding: 18px;
  border: 1px dashed var(--am-border-strong);
  border-radius: var(--am-radius-sm);
  color: var(--am-text-subtle);
  text-align: center;
}

.workflow-color-map-editor__json {
  display: grid;
  gap: 6px;
  color: var(--am-text-subtle);
  font-size: 12px;
  font-weight: 700;
}

.workflow-color-map-editor__json textarea {
  min-height: 210px;
  padding: 10px;
  resize: vertical;
  font-family: Consolas, 'Courier New', monospace;
  font-size: 12px;
  line-height: 1.5;
}

.workflow-color-map-editor__error {
  margin: 0;
  padding: 9px 10px;
  border-radius: var(--am-radius-sm);
  color: var(--am-danger);
  background: color-mix(in srgb, var(--am-danger) 10%, transparent);
  font-size: 12px;
  line-height: 1.45;
}

@media (max-width: 620px) {
  .workflow-color-map-editor__header {
    display: none;
  }

  .workflow-color-map-editor__row {
    grid-template-columns: 1fr;
  }

  .workflow-color-map-palette {
    grid-column: 1;
    grid-template-columns: repeat(8, minmax(20px, 1fr));
    justify-content: stretch;
  }

  .workflow-color-map-palette__color {
    width: 100%;
  }
}
</style>
