<template>
  <div
    class="file-picker"
    :class="{ 'file-picker--dragging': dragging, 'file-picker--disabled': disabled, 'file-picker--has-file': selectedFiles.length > 0 }"
    @dragenter.prevent="activateDrag"
    @dragover.prevent="activateDrag"
    @dragleave.prevent="deactivateDrag"
    @drop.prevent="handleDrop"
  >
    <Label class="file-picker__label" :for="inputId">{{ label }}</Label>
    <VisuallyHidden>
      <input
        :id="inputId"
        ref="inputElement"
        class="file-picker__native-input"
        type="file"
        :accept="accept"
        :multiple="multiple"
        :disabled="disabled"
        tabindex="-1"
        @change="handleInputChange"
      />
    </VisuallyHidden>

    <div class="file-picker__dropzone" @click="openFileDialog">
      <div class="file-picker__icon" aria-hidden="true">
        <component :is="iconComponent" :size="22" />
      </div>
      <div class="file-picker__content">
        <strong>{{ selectedSummary }}</strong>
        <span>{{ description || t('common.filePicker.dropHint') }}</span>
        <ul v-if="selectedFiles.length > 0" class="file-picker__files">
          <li v-for="file in selectedFiles" :key="`${file.name}-${file.size}-${file.lastModified}`">
            <span class="file-picker__file-name">{{ file.name }}</span>
            <span class="file-picker__file-size">{{ formatFileSize(file.size) }}</span>
          </li>
        </ul>
      </div>
      <div class="file-picker__actions">
        <Button size="sm" variant="secondary" :disabled="disabled" @click.stop="openFileDialog">
          {{ selectedFiles.length > 0 ? t('common.filePicker.replace') : t('common.filePicker.choose') }}
        </Button>
        <Button v-if="selectedFiles.length > 0" size="sm" variant="ghost" :disabled="disabled" @click.stop="clearFiles">
          <X :size="14" />
          {{ t('common.filePicker.clear') }}
        </Button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, useId } from 'vue'
import { FileArchive, ImageUp, UploadCloud, X } from '@lucide/vue'
import { Label, VisuallyHidden } from 'reka-ui'
import { useI18n } from 'vue-i18n'

import Button from './Button.vue'

type FilePickerIcon = 'upload' | 'image' | 'archive'
type FilePickerValue = File | File[] | null

const props = withDefaults(
  defineProps<{
    modelValue?: FilePickerValue
    id?: string
    label: string
    description?: string
    accept?: string
    multiple?: boolean
    disabled?: boolean
    icon?: FilePickerIcon
  }>(),
  {
    modelValue: null,
    id: '',
    description: '',
    accept: '',
    multiple: false,
    disabled: false,
    icon: 'upload',
  },
)

const emit = defineEmits<{
  'update:modelValue': [value: FilePickerValue]
  change: [value: FilePickerValue]
}>()

const { t } = useI18n()
const generatedInputId = useId()
const inputElement = ref<HTMLInputElement | null>(null)
const dragging = ref(false)

const inputId = computed(() => props.id || generatedInputId)
const selectedFiles = computed(() => {
  if (Array.isArray(props.modelValue)) return props.modelValue
  return props.modelValue ? [props.modelValue] : []
})
const selectedSummary = computed(() => {
  if (selectedFiles.value.length === 0) return t('common.filePicker.noFile')
  if (selectedFiles.value.length === 1) return selectedFiles.value[0].name
  return t('common.filePicker.fileCount', { count: selectedFiles.value.length })
})
const iconComponent = computed(() => {
  if (props.icon === 'image') return ImageUp
  if (props.icon === 'archive') return FileArchive
  return UploadCloud
})

function openFileDialog(): void {
  if (props.disabled) return
  inputElement.value?.click()
}

function handleInputChange(event: Event): void {
  const files = Array.from((event.target as HTMLInputElement).files ?? [])
  applyFiles(files)
}

function handleDrop(event: DragEvent): void {
  dragging.value = false
  if (props.disabled) return
  const files = Array.from(event.dataTransfer?.files ?? [])
  applyFiles(files)
}

function applyFiles(files: File[]): void {
  const acceptedFiles = files.filter((file) => matchesAccept(file))
  if (acceptedFiles.length === 0) return
  const nextValue = props.multiple ? acceptedFiles : acceptedFiles[0]
  emit('update:modelValue', nextValue)
  emit('change', nextValue)
}

function clearFiles(): void {
  emit('update:modelValue', null)
  emit('change', null)
  if (inputElement.value) inputElement.value.value = ''
}

function activateDrag(): void {
  if (!props.disabled) dragging.value = true
}

function deactivateDrag(): void {
  dragging.value = false
}

function matchesAccept(file: File): boolean {
  const acceptRules = props.accept.split(',').map((item) => item.trim().toLowerCase()).filter(Boolean)
  if (acceptRules.length === 0) return true
  const fileName = file.name.toLowerCase()
  const fileType = file.type.toLowerCase()
  return acceptRules.some((rule) => {
    if (rule.startsWith('.')) return fileName.endsWith(rule)
    if (rule.endsWith('/*')) return fileType.startsWith(rule.slice(0, -1))
    return fileType === rule
  })
}

function formatFileSize(size: number): string {
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / 1024 / 1024).toFixed(1)} MB`
}
</script>