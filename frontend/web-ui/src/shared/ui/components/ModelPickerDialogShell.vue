<template>
  <div v-if="open" class="model-picker-shell__backdrop" @click="$emit('close')">
    <div class="model-picker-shell" role="dialog" aria-modal="true" :aria-label="title" @click.stop @keydown.esc.prevent="$emit('close')">
      <header class="model-picker-shell__header">
        <div>
          <p class="page-kicker">{{ kicker }}</p>
          <h2>{{ title }}</h2>
          <p class="model-picker-shell__description">{{ description }}</p>
        </div>
        <button type="button" class="model-picker-shell__close" :title="closeLabel" :aria-label="closeLabel" @click="$emit('close')">
          <X :size="16" />
        </button>
      </header>

      <div class="model-picker-shell__toolbar">
        <span class="model-picker-shell__label">{{ taskTypeLabel }}</span>
        <div class="model-picker-shell__tabs" role="tablist" :aria-label="taskTypeLabel">
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
              <LoaderCircle v-if="loading" class="model-picker-shell__spinner" :size="16" aria-label="正在更新" />
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
  </div>
</template>

<script setup lang="ts">
import { LoaderCircle, X } from '@lucide/vue'

defineProps<{
  open: boolean
  loading: boolean
  kicker: string
  title: string
  description: string
  closeLabel: string
  taskTypeLabel: string
  taskTypeOptions: Array<{ label: string; value: string }>
  selectedTaskType: string
  listTitle: string
  listCount: number
  detailTitle: string
}>()

defineEmits<{ close: []; 'change-task-type': [taskType: string] }>()
</script>

<style scoped>
.model-picker-shell__backdrop { position: fixed; inset: 0; z-index: 80; display: grid; place-items: center; padding: 18px; background: rgb(16 20 24 / 0.38); }
.model-picker-shell { display: grid; grid-template-rows: auto auto minmax(0, 1fr); gap: 12px; width: min(1120px, calc(100vw - 36px)); height: min(820px, calc(100vh - 36px)); padding: 16px; border: 1px solid var(--line); border-radius: 10px; background: var(--surface); box-shadow: 0 24px 48px rgb(0 0 0 / 0.18); }
.model-picker-shell__header, .model-picker-shell__toolbar, .model-picker-shell__section-heading, .model-picker-shell__heading-meta { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.model-picker-shell__header { align-items: flex-start; }
.model-picker-shell__header h2, .model-picker-shell__header p { margin: 0; }
.model-picker-shell__description { margin-top: 8px !important; color: var(--muted); }
.model-picker-shell__close { display: inline-flex; align-items: center; justify-content: center; width: 34px; height: 34px; border: 1px solid var(--line-strong); border-radius: 8px; color: var(--text); background: var(--button-secondary-bg); cursor: pointer; }
.model-picker-shell__label { color: var(--muted); font-size: 12px; font-weight: 700; }
.model-picker-shell__tabs { display: flex; align-items: center; justify-content: flex-end; gap: 8px; flex-wrap: wrap; margin-left: auto; }
.model-picker-shell__tab { display: inline-flex; align-items: center; justify-content: center; min-height: 34px; padding: 0 12px; border: 1px solid var(--line-strong); border-radius: 999px; color: var(--muted); background: var(--button-secondary-bg); cursor: pointer; font-weight: 700; }
.model-picker-shell__tab.is-active { border-color: var(--accent); color: #fff; background: var(--accent); }
.model-picker-shell__body { display: grid; grid-template-columns: minmax(0, 1.05fr) minmax(0, 1fr); gap: 14px; min-height: 0; }
.model-picker-shell__column { display: grid; grid-template-rows: auto minmax(0, 1fr); gap: 12px; min-width: 0; min-height: 0; overflow: hidden; }
.model-picker-shell__count { display: inline-flex; align-items: center; justify-content: center; min-width: 28px; min-height: 24px; padding: 0 8px; border-radius: 999px; color: var(--muted); background: var(--button-secondary-bg); font-size: 12px; font-weight: 700; }
.model-picker-shell__spinner { color: var(--accent); animation: model-picker-shell-spin .8s linear infinite; }
@keyframes model-picker-shell-spin { to { transform: rotate(360deg); } }
@media (max-width: 960px) { .model-picker-shell { width: min(100%, calc(100vw - 24px)); height: min(820px, calc(100vh - 24px)); } .model-picker-shell__body { grid-template-columns: 1fr; } }
@media (prefers-reduced-motion: reduce) { .model-picker-shell__spinner { animation: none; } }
</style>
