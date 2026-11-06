<template>
  <TooltipProvider :delay-duration="250">
    <TooltipRoot>
      <TooltipTrigger as-child>
        <span class="dataset-counts" :class="{ 'dataset-counts--labeled': showLabels }" role="group" tabindex="0" :aria-label="description">
          <span v-if="summary" class="dataset-counts__summary" aria-hidden="true">{{ items.map(item => item.summary).join(' / ') }}</span>
          <template v-else><span
            v-for="item in items"
            :key="item.key"
            class="dataset-counts__value"
            aria-hidden="true"
          >
            <span v-if="showLabels" class="dataset-counts__heading">{{ item.heading }}</span>
            <span class="dataset-counts__number">{{ item.count?.toLocaleString() ?? '—' }}</span>
          </span></template>
        </span>
      </TooltipTrigger>
      <TooltipPortal>
        <TooltipContent class="dataset-counts-tooltip" side="top" :side-offset="6" :collision-padding="12">
          <div v-for="item in items" :key="item.key">{{ item.label }}</div>
        </TooltipContent>
      </TooltipPortal>
    </TooltipRoot>
  </TooltipProvider>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { TooltipContent, TooltipPortal, TooltipProvider, TooltipRoot, TooltipTrigger } from 'reka-ui'
import type { DatasetCountItem } from '../dataset-counts'

const props = defineProps<{
  items: DatasetCountItem[]
  showLabels?: boolean
  summary?: boolean
}>()
const description = computed(() =>
  props.items.map((item) => item.label).join('；'),
)
</script>

<style>
.dataset-workspace .dataset-counts, .dataset-counts {
  display: inline-flex;
  align-items: center;
  max-width: 100%;
  gap: 16px;
  vertical-align: middle;
  font-family: inherit;
  border-radius: 6px;
}
.dataset-counts:focus-visible {
  outline: 2px solid var(--am-input-focus-ring);
  outline-offset: 2px;
}
.dataset-workspace .dataset-counts > .dataset-counts__summary {
  min-width: 0;
  font-family: inherit;
  font-size: 14px;
  font-weight: 400;
  line-height: 21px;
  color: var(--am-text);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.dataset-counts-tooltip {
  z-index: 120;
  max-width: min(320px, calc(100vw - 24px));
  padding: 8px 12px;
  border: 1px solid var(--am-border-strong);
  border-radius: 6px;
  background: var(--am-surface-raised);
  color: var(--am-text);
  box-shadow: 0 2px 8px rgb(0 0 0 / 0.12);
  font-size: 13px;
  font-weight: 400;
  line-height: 1.6;
  overflow-wrap: anywhere;
}
.dataset-counts > .dataset-counts__value.dataset-counts__value {
  display: inline-grid;
  gap: 4px;
  flex: 0 1 auto;
  min-width: 0;
  color: var(--am-text);
  font-size: 14px;
  font-weight: 400;
  font-variant-numeric: tabular-nums;
  line-height: 20px;
  text-align: right;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.dataset-counts > .dataset-counts__value > .dataset-counts__number {
  font: inherit;
  color: inherit;
  overflow: hidden;
  text-overflow: ellipsis;
}
.dataset-counts > .dataset-counts__value > .dataset-counts__heading {
  font-size: 12px;
  font-weight: 400;
  color: var(--am-text-muted);
}
.dataset-counts--labeled {
  flex-wrap: wrap;
  gap: 4px 16px;
}
</style>
