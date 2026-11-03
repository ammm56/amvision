<template>
  <section class="debug-summary">
    <div class="debug-controls">
      <label
        >{{ zh ? '提取证据' : 'Extraction evidence'
        }}<select
          :value="selectedId"
          @change="emit('select', ($event.target as HTMLSelectElement).value)"
        >
          <option v-for="item in items" :key="item.id" :value="item.id">
            {{ item.featureId }} · {{ item.nodeId }}
          </option>
        </select></label
      >
      <label v-for="layer in availableLayers" :key="layer.key"
        ><input
          type="checkbox"
          :checked="layers[layer.key]"
          @change="
            emit('layers', {
              ...layers,
              [layer.key]: ($event.target as HTMLInputElement).checked,
            })
          "
        />{{ layer.label }}</label
      >
    </div>
    <p v-if="error" role="alert">{{ error }}</p>
    <template v-if="current">
      <p role="status">
        {{
          current.state === 'ready'
            ? zh
              ? '同次冻结证据'
              : 'Captured in this run'
            : current.reason
        }}
        ·
        {{
          current.complete
            ? zh
              ? '选择阶段已完成'
              : 'Selection completed'
            : zh
              ? '选择阶段未完成'
              : 'Selection incomplete'
        }}<span v-if="current.measurementReason">
          · {{ current.measurementReason }}</span
        >
      </p>
      <p v-if="current.failureField">
        {{ current.failureField
        }}<template v-if="current.requiredBytes != null">
          · {{ current.requiredBytes }} B</template
        >
      </p>
      <div v-if="current.grid" class="legend">
        <span v-for="(name, i) in legend" :key="name"
          ><i :style="{ background: colors[i] }" />{{ name }}</span
        >
      </div>
      <div v-if="current.state === 'ready'" class="debug-controls">
        <label
          >{{ zh ? '证据类别' : 'Evidence kind'
          }}<select v-model="kind">
            <option
              v-for="entry in kinds"
              :key="entry.value"
              :value="entry.value"
            >
              {{ entry.label }}
            </option>
          </select></label
        ><label
          >{{ zh ? '序号' : 'Index'
          }}<input
            type="number"
            min="0"
            :max="rowCount - 1"
            :value="selection?.kind === kind ? selection.index : ''"
            @change="
              choose(Number(($event.target as HTMLInputElement).value))
            " /></label
        ><button
          :aria-label="zh ? '上一页' : 'Previous page'"
          :disabled="page === 0"
          @click="page--"
        >
          <ChevronLeft :size="16" /></button
        ><span>{{ page + 1 }} / {{ pages }}</span
        ><button
          :aria-label="zh ? '下一页' : 'Next page'"
          :disabled="page + 1 >= pages"
          @click="page++"
        >
          <ChevronRight :size="16" />
        </button>
      </div>
      <table v-if="current.state === 'ready'">
        <thead>
          <tr>
            <th>{{ zh ? '序号' : 'Index' }}</th>
            <th>{{ zh ? '统计与来源' : 'Statistics and source' }}</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="index in rows"
            :key="index"
            :class="{
              selected: selection?.kind === kind && selection.index === index,
            }"
          >
            <td>
              <button
                :aria-pressed="
                  selection?.kind === kind && selection.index === index
                "
                @click="choose(index)"
              >
                {{ index }}
              </button>
            </td>
            <td>{{ details(index) }}</td>
          </tr>
        </tbody>
      </table>
    </template>
  </section>
</template>
<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { ChevronLeft, ChevronRight } from '@lucide/vue'
import type {
  DebugEvidence,
  DebugLayers,
  DebugSelection,
} from './boundary-debug'
const props = defineProps<{
  items: DebugEvidence[]
  selectedId: string
  layers: DebugLayers
  selection: DebugSelection | null
  error: string
}>()
const emit = defineEmits<{
  select: [id: string]
  layers: [value: DebugLayers]
  pick: [value: DebugSelection]
}>()
const { locale } = useI18n(),
  zh = computed(() => locale.value === 'zh-CN'),
  page = ref(0),
  kind = ref<DebugSelection['kind']>('cell')
const current = computed(() =>
  props.items.find((d) => d.id === props.selectedId),
)
const colors = [
  '#0f9e73',
  '#2e70cc',
  '#737f8c',
  '#d9801f',
  '#3d424a',
  '#b8479e',
]
const legend = computed(() =>
  zh.value
    ? ['选中实测格', '其他前景', '背景', '观测不足', '无点', '闭运算连接格']
    : [
        'Selected observed',
        'Other foreground',
        'Background',
        'Insufficient observations',
        'Empty',
        'Closing connection',
      ],
)
const availableLayers = computed(() => {
  const d = current.value
  return [
    ...(d?.grid
      ? [{ key: 'grid' as const, label: zh.value ? '完整格网' : 'Full grid' }]
      : []),
    ...(d?.arrays.profile_positions
      ? [
          {
            key: 'profiles' as const,
            label: zh.value ? '四侧剖面' : 'Four profiles',
          },
        ]
      : []),
    ...(d?.arrays.metric_uv
      ? [
          {
            key: 'partition' as const,
            label: zh.value ? '距离分区' : 'Distance partition',
          },
        ]
      : []),
    ...(d?.arrays.candidate_positions
      ? [
          {
            key: 'candidates' as const,
            label: zh.value ? '全部候选' : 'All candidates',
          },
        ]
      : []),
  ]
})
const kinds = computed(() => {
  const a = current.value?.arrays
  return [
    ...(a?.counts
      ? [{ value: 'cell' as const, label: zh.value ? '格子' : 'Cells' }]
      : []),
    ...(a?.profile_positions
      ? [
          {
            value: 'profile' as const,
            label: zh.value ? '剖面点' : 'Profile points',
          },
        ]
      : []),
    ...(a?.candidate_closed
      ? [
          {
            value: 'candidate' as const,
            label: zh.value ? '候选段' : 'Candidates',
          },
        ]
      : []),
    ...(a?.metric_rows
      ? [
          {
            value: 'metric' as const,
            label: zh.value ? '分区点' : 'Partition points',
          },
        ]
      : []),
  ]
})
const rowCount = computed(() => {
  const a = current.value?.arrays
  return (
    a?.[
      {
        cell: 'counts',
        profile: 'profile_positions',
        candidate: 'candidate_closed',
        metric: 'metric_rows',
      }[kind.value]
    ]?.count ?? 0
  )
})
const pages = computed(() => Math.max(1, Math.ceil(rowCount.value / 20))),
  rows = computed(() =>
    Array.from(
      { length: Math.min(20, Math.max(0, rowCount.value - page.value * 20)) },
      (_, i) => page.value * 20 + i,
    ),
  )
watch(
  kinds,
  (list) => {
    if (!list.some((k) => k.value === kind.value))
      kind.value = list[0]?.value ?? 'cell'
  },
  { immediate: true },
)
watch(
  () => [props.selectedId, kind.value],
  () => {
    page.value = 0
  },
  { flush: 'sync' },
)
watch(
  () => props.selection,
  (selection) => {
    if (selection) {
      kind.value = selection.kind
      page.value = Math.floor(selection.index / 20)
    }
  },
  { flush: 'post' },
)
function choose(index: number) {
  if (Number.isSafeInteger(index) && index >= 0 && index < rowCount.value)
    emit('pick', { kind: kind.value, index })
}
function details(index: number) {
  const d = current.value!,
    a = d.arrays,
    get = (name: string, c = 0) => a[name]?.get(index, c)
  if (kind.value === 'cell') {
    const observed = get('counts')! > 0
    return `U/V ${Math.floor(index / d.grid!.shape[1]!)}/${index % d.grid!.shape[1]!} · n=${get('counts')} · h=${observed ? get('heights') : '-'} · span=${observed ? get('spread') : '-'} · selected=${get('selected')}`
  }
  if (kind.value === 'profile')
    return `${zh.value ? '格来源' : 'Cells'} ${get('profile_cells', 0)}/${get('profile_cells', 1)} · ${zh.value ? '权重' : 'Weights'} ${get('profile_weights', 0)}/${get('profile_weights', 1)} · ${['threshold-interpolation', 'cell-edge', 'missing-neighbor', 'not-bracketed'][get('profile_kinds')!]}`
  if (kind.value === 'metric') {
    const row = get('metric_rows')!
    return `${zh.value ? '原始行' : 'Source row'} ${a.input_source_indices!.get(row)} · component=${get('metric_labels')} · UV ${get('metric_uv', 0)}, ${get('metric_uv', 1)}`
  }
  const events = a.selection_events,
    parts: string[] = []
  for (let t = 0; t < d.targetIds.length; t++) {
    let state = zh.value ? '未评价' : 'Not evaluated'
    if (events)
      for (let i = 0; i < events.count; i++)
        if (events.get(i, 0) === t && events.get(i, 1) === index)
          state = (
            zh.value
              ? ['未命中', '命中', '闭环拒绝']
              : ['No match', 'Matched', 'Closed rejected']
          )[events.get(i, 2)]!
    parts.push(`${d.targetIds[t]}: ${state}`)
  }
  return `${a.candidate_offsets!.get(index + 1) - a.candidate_offsets!.get(index)} ${zh.value ? '点' : 'points'} · ${parts.join(' · ')}`
}
</script>
<style scoped>
.debug-summary {
  font-size: 12px;
  min-width: 0;
}
.debug-controls {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
  padding: 6px 0;
}
.debug-controls label {
  display: flex;
  align-items: center;
  gap: 4px;
  min-width: 0;
}
.debug-controls input[type='number'] {
  width: 88px;
}
.debug-controls select {
  max-width: 240px;
  min-width: 0;
}
button {
  display: inline-grid;
  place-items: center;
  min-width: 28px;
  min-height: 28px;
  background: var(--am-surface);
  color: var(--am-text);
  border: 1px solid var(--am-border);
  border-radius: 4px;
}
table {
  width: 100%;
  border-collapse: collapse;
}
th,
td {
  text-align: left;
  padding: 5px;
  border-bottom: 1px solid var(--am-border);
  overflow-wrap: anywhere;
}
.selected {
  background: var(--am-surface-soft);
}
.legend {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
}
.legend span {
  display: flex;
  align-items: center;
  gap: 4px;
}
.legend i {
  width: 10px;
  height: 10px;
}
p {
  overflow-wrap: anywhere;
}
</style>
