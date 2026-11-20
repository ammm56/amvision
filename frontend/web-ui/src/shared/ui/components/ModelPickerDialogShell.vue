<template>
  <div v-if="open" class="model-picker-shell__backdrop" :style="{ zIndex: order, background: covered ? 'transparent' : undefined }" @click.self="close">
    <div
      ref="dialog"
      class="model-picker-shell"
      :class="{ 'is-compact': compact, 'has-footer': $slots.footer }"
      role="dialog"
      aria-modal="true"
      :aria-label="title"
      tabindex="-1"
      @keydown.esc.stop.prevent="close"
      @keydown.tab="trapFocus"
    >
      <header class="model-picker-shell__header">
        <div>
          <h2>{{ title }}</h2>
          <p v-if="description" class="model-picker-shell__description">{{ description }}</p>
        </div>
        <button type="button" class="model-picker-shell__close" :title="closeLabel" :aria-label="closeLabel" @click="close">
          <X :size="16" />
        </button>
      </header>

      <div class="model-picker-shell__content">
        <div class="model-picker-shell__toolbar">
          <span v-if="taskTypeLabel" class="model-picker-shell__label">{{ taskTypeLabel }}</span>
          <div class="model-picker-shell__tabs" role="tablist" :aria-label="taskTypeLabel || title">
            <button v-for="option in taskTypeOptions" :key="option.value" type="button" role="tab" class="model-picker-shell__tab" :class="{ 'is-active': option.value === selectedTaskType }" :aria-selected="option.value === selectedTaskType" @click.stop="$emit('change-task-type', option.value)">
              {{ option.label }}
            </button>
          </div>
        </div>

        <div class="model-picker-shell__body" :aria-busy="loading">
          <section class="model-picker-shell__column">
            <header class="model-picker-shell__section-heading">
              <strong>{{ listTitle }}</strong>
              <span class="model-picker-shell__heading-meta">
                <LoaderCircle v-if="loading" class="model-picker-shell__spinner" :size="16" :aria-label="t('common.updating')" />
                <span class="model-picker-shell__count">{{ listCount }}</span>
              </span>
            </header>
            <slot name="list" />
          </section>
          <section class="model-picker-shell__column">
            <header class="model-picker-shell__section-heading"><strong>{{ detailTitle }}</strong></header>
            <slot name="detail" />
          </section>
        </div>
      </div>
      <footer v-if="$slots.footer" class="model-picker-shell__footer">
        <slot name="footer" />
      </footer>
    </div>
  </div>
</template>

<script setup lang="ts">
import { LoaderCircle, X } from '@lucide/vue'
import { ref, watch } from 'vue'
import { useTranslation } from '@/platform/i18n'
import { useModalLayer } from './modal-layer'

const { t } = useTranslation()

const props = defineProps<{
  open: boolean
  loading: boolean
  compact?: boolean
  title: string
  description?: string
  closeLabel: string
  taskTypeLabel?: string
  taskTypeOptions: Array<{ label: string; value: string }>
  selectedTaskType: string
  listTitle: string
  listCount: number
  detailTitle: string
}>()

const emit = defineEmits<{ close: []; 'change-task-type': [taskType: string] }>()
const dialog = ref<HTMLElement | null>(null)
const { activate, deactivate, trapFocus, isTop, order, covered } = useModalLayer(dialog)

function close(): void {
  if (isTop()) emit('close')
}

watch(() => props.open, open => {
  if (open) void activate()
  else deactivate()
}, { immediate: true })
</script>

<style scoped>
.model-picker-shell__backdrop { position: fixed; inset: 0; z-index: 80; display: grid; place-items: center; padding: 18px; background: var(--am-overlay); }
.model-picker-shell { display: grid; grid-template-rows: auto minmax(0, 1fr); gap: 12px; width: min(1120px, calc(100vw - 36px)); height: min(820px, calc(100vh - 36px)); padding: 16px; border: 1px solid var(--am-border); border-radius: 10px; background: var(--am-surface); box-shadow: var(--am-shadow-modal); }
.model-picker-shell.is-compact { height: min(680px, calc(100vh - 36px)); }
.model-picker-shell.has-footer { grid-template-rows: auto minmax(0, 1fr) auto; }
.model-picker-shell__footer { display: flex; flex-wrap: wrap; align-items: center; justify-content: flex-end; gap: 10px; padding-block-start: 12px; border-top: 1px solid var(--am-border); }
.model-picker-shell__header, .model-picker-shell__toolbar, .model-picker-shell__section-heading, .model-picker-shell__heading-meta { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.model-picker-shell__header { align-items: flex-start; }
.model-picker-shell__content { display: grid; grid-template-rows: auto minmax(0, 1fr); gap: 12px; min-height: 0; }
.model-picker-shell__section-heading { min-height: 24px; }
.model-picker-shell__section-heading > strong { line-height: 24px; }
.model-picker-shell__header h2, .model-picker-shell__header p { margin: 0; }
.model-picker-shell__description { margin-top: 8px !important; color: var(--am-text-muted); }
.model-picker-shell__close { display: inline-flex; align-items: center; justify-content: center; width: 34px; height: 34px; border: 1px solid var(--am-border-strong); border-radius: 8px; color: var(--am-text); background: var(--am-surface); cursor: pointer; }
.model-picker-shell__label { color: var(--am-text-muted); font-size: 12px; font-weight: 700; }
.model-picker-shell__tabs { display: flex; align-items: center; justify-content: flex-end; gap: 8px; flex-wrap: wrap; margin-left: auto; }
.model-picker-shell__tab { display: inline-flex; align-items: center; justify-content: center; min-height: 34px; padding: 0 12px; border: 1px solid var(--am-border-strong); border-radius: 999px; color: var(--am-text-muted); background: var(--am-surface); cursor: pointer; font-weight: 700; }
.model-picker-shell__tab.is-active { border-color: var(--am-action-primary); color: var(--am-on-action); background: var(--am-action-primary); }
.model-picker-shell__body { display: grid; grid-template-columns: minmax(0, 1.05fr) minmax(0, 1fr); gap: 14px; min-height: 0; }
.model-picker-shell__column { display: grid; grid-template-rows: auto minmax(0, 1fr); gap: 12px; min-width: 0; min-height: 0; overflow: hidden; }
.model-picker-shell__count { display: inline-flex; align-items: center; justify-content: center; min-width: 28px; min-height: 24px; padding: 0 8px; border-radius: 999px; color: var(--am-text-muted); background: var(--am-surface); font-size: 12px; font-weight: 700; }
.model-picker-shell__spinner { color: var(--am-action-primary); animation: model-picker-shell-spin .8s linear infinite; }
@keyframes model-picker-shell-spin { to { transform: rotate(360deg); } }
@media (max-width: 960px) {
  .model-picker-shell,
  .model-picker-shell.is-compact {
    width: min(100%, calc(100vw - 36px));
    height: min(820px, calc(100vh - 36px));
    overflow: hidden;
  }

  .model-picker-shell__content {
    display: block;
    min-height: 0;
    overflow-x: hidden;
    overflow-y: auto;
    overscroll-behavior: contain;
  }

  .model-picker-shell__body {
    margin-top: 12px;
    grid-template-columns: 1fr;
  }

  .model-picker-shell__column {
    grid-template-rows: auto auto;
    min-height: auto;
    overflow: visible;
  }
}
@media (prefers-reduced-motion: reduce) { .model-picker-shell__spinner { animation: none; } }
</style>
