<template>
  <div ref="viewport" class="runtime-canvas" @pointerdown="startPan">
    <div :style="{ width: `${bounds.width * zoom}px`, height: `${bounds.height * zoom}px` }">
      <div class="runtime-canvas__world" :style="{ width: `${bounds.width}px`, height: `${bounds.height}px`, transform: `scale(${zoom})` }">
        <div v-for="group in template.groups ?? []" :key="group.group_id" class="runtime-canvas__group"
          :style="{ left: `${group.rect.x + bounds.offsetX}px`, top: `${group.rect.y + bounds.offsetY}px`, width: `${group.rect.width}px`, height: `${group.rect.height}px` }">{{ group.name }}</div>
        <svg class="runtime-canvas__links" :width="bounds.width" :height="bounds.height" aria-hidden="true">
          <path v-for="edge in links" :key="edge.id" :d="edge.path" />
        </svg>
        <article v-for="node in nodes" :key="node.node_id" class="runtime-canvas__node" :class="{ 'is-disabled': !node.enabled }" :data-node-id="node.node_id"
          :style="{ left: `${node.x}px`, top: `${node.y}px`, width: `${node.width}px` }">
          <header><strong>{{ node.title }}</strong><small>{{ node.node_type_id }}</small></header>
          <div class="runtime-canvas__ports">
            <div><span v-for="port in node.inputs" :key="port">● {{ port }}</span></div>
            <div><span v-for="port in node.outputs" :key="port">{{ port }} ●</span></div>
          </div>
          <template v-for="display in nodeDisplays(node.node_id)" :key="display.outputName">
            <WorkflowNodePreviewDisplay :display="display" :fallback-title="node.title" :tooltip="display.title"
              @open-display="emit('openDisplay', $event)" @open-image="emit('openImage', $event)" />
          </template>
          <small v-if="invocations[node.node_id] && invocations[node.node_id] !== node.node_id" class="runtime-canvas__identity">{{ invocations[node.node_id] }}</small>
          <details v-if="Object.keys(node.parameters).length" class="runtime-canvas__parameters">
            <summary>{{ t('workflowEditor.runtimePreview.parameters') }}</summary><pre>{{ JSON.stringify(node.parameters, null, 2) }}</pre>
          </details>
        </article>
        <article v-for="note in notes" :key="note.note_id" class="runtime-canvas__note"
          :style="{ left: `${note.rect.x + bounds.offsetX}px`, top: `${note.rect.y + bounds.offsetY}px`, width: `${note.rect.width}px` }">
          <strong>{{ note.title }}</strong><div v-if="!note.collapsed" class="workflow-graph-note__markdown" v-html="note.html" />
        </article>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue'
import { useTranslation } from '@/platform/i18n'
import type { WorkflowGraphTemplate, NodeDefinition, FlowApplication, WorkflowJsonObject } from '../types'
import type { PreviewNodeDisplay, PreviewViewerImage } from '../preview/useWorkflowPreviewDisplays'
import WorkflowNodePreviewDisplay from './WorkflowNodePreviewDisplay.vue'
import { renderWorkflowNoteMarkdown } from '../notes/workflowNoteMarkdown'

const props = defineProps<{
  template: WorkflowGraphTemplate; application: FlowApplication; definitions: NodeDefinition[]; zoom: number
  displays: Record<string, PreviewNodeDisplay>; invocations: Record<string, string>
}>()
const emit = defineEmits<{ openDisplay: [display: PreviewNodeDisplay]; openImage: [image: PreviewViewerImage] }>()
const { t } = useTranslation()
const viewport = ref<HTMLElement | null>(null)
const notes = computed(() => (props.template.notes ?? []).map((note) => ({ ...note, html: renderWorkflowNoteMarkdown(note.content) })))
const number = (value: unknown, fallback: number) => typeof value === 'number' && Number.isFinite(value) ? value : fallback
const object = (value: unknown): WorkflowJsonObject => value && typeof value === 'object' && !Array.isArray(value) ? value as WorkflowJsonObject : {}
const rawNodes = computed(() => {
  const graph = props.template.nodes.map((node, index) => {
    const definition = props.definitions.find((item) => item.node_type_id === node.node_type_id)
    return { ...node,
      title: String(node.ui_state.title || definition?.display_name || node.node_type_id),
      x: number(node.ui_state.x, index * 300), y: number(node.ui_state.y, 0),
      width: Math.max(180, number(node.ui_state.width, 256)),
      inputs: [...new Set([...(definition?.input_ports.map((port) => port.name) ?? []),
        ...props.template.edges.filter((edge) => edge.target_node_id === node.node_id).map((edge) => edge.target_port),
        ...props.template.template_inputs.filter((input) => input.target_node_id === node.node_id).map((input) => input.target_port)])],
      outputs: [...new Set([...(definition?.output_ports.map((port) => port.name) ?? []),
        ...props.template.edges.filter((edge) => edge.source_node_id === node.node_id).map((edge) => edge.source_port)])],
    }
  })
  if (!graph.length) return graph
  const positions = object(object(props.application.metadata.workflow_graph_editor).boundary_positions)
  const minX = Math.min(...graph.map((node) => node.x)), minY = Math.min(...graph.map((node) => node.y))
  const maxX = Math.max(...graph.map((node) => node.x + node.width))
  return [...graph, ...(['entry', 'result'] as const).map((kind) => {
    const position = object(positions[kind])
    const ports = props.application.bindings.filter((binding) => binding.direction === (kind === 'entry' ? 'input' : 'output')).map((binding) => binding.binding_id)
    return { node_id: `app-${kind}-boundary`, node_type_id: '', title: kind === 'entry' ? 'App Entry' : 'App Result',
      parameters: {}, ui_state: {}, metadata: {}, enabled: true,
      x: number(position.x, kind === 'entry' ? minX - 320 : maxX + 140), y: number(position.y, minY), width: 250,
      inputs: kind === 'entry' ? [] : ports, outputs: kind === 'entry' ? ports : [],
    }
  })]
})
const bounds = computed(() => {
  const rectangles = [...rawNodes.value.map((node) => ({ ...node, height: 600 })),
    ...(props.template.notes ?? []).map((note) => note.rect), ...(props.template.groups ?? []).map((group) => group.rect)]
  const offsetX = 40 - Math.min(0, ...rectangles.map((rect) => rect.x))
  const offsetY = 40 - Math.min(0, ...rectangles.map((rect) => rect.y))
  return { offsetX, offsetY,
    width: Math.max(1200, ...rectangles.map((rect) => rect.x + rect.width + offsetX + 100)),
    height: Math.max(800, ...rectangles.map((rect) => rect.y + rect.height + offsetY + 100)),
  }
})
const nodes = computed(() => rawNodes.value.map((node) => ({ ...node, x: node.x + bounds.value.offsetX, y: node.y + bounds.value.offsetY })))
const graphEdges = computed(() => [...props.template.edges, ...props.application.bindings.flatMap((binding) => {
  if (binding.direction === 'input') {
    const port = props.template.template_inputs.find((input) => input.input_id === binding.template_port_id)
    return port ? [{ edge_id: `entry:${binding.binding_id}`, source_node_id: 'app-entry-boundary', source_port: binding.binding_id, target_node_id: port.target_node_id, target_port: port.target_port }] : []
  }
  const port = props.template.template_outputs.find((output) => output.output_id === binding.template_port_id)
  return port ? [{ edge_id: `result:${binding.binding_id}`, source_node_id: port.source_node_id, source_port: port.source_port, target_node_id: 'app-result-boundary', target_port: binding.binding_id }] : []
})])
const links = computed(() => graphEdges.value.flatMap((edge) => {
  const source = nodes.value.find((node) => node.node_id === edge.source_node_id)
  const target = nodes.value.find((node) => node.node_id === edge.target_node_id)
  if (!source || !target) return []
  const x1 = source.x + source.width, x2 = target.x
  const y1 = source.y + 69 + Math.max(0, source.outputs.indexOf(edge.source_port)) * 22
  const y2 = target.y + 69 + Math.max(0, target.inputs.indexOf(edge.target_port)) * 22
  const bend = Math.max(45, Math.abs(x2 - x1) * 0.45)
  return [{ id: edge.edge_id, path: `M${x1},${y1} C${x1 + bend},${y1} ${x2 - bend},${y2} ${x2},${y2}` }]
}))
function nodeDisplays(nodeId: string) { return Object.values(props.displays).filter((display) => display.nodeId === nodeId) }
let stopPan = () => {}
function startPan(event: PointerEvent) {
  if (event.button !== 0 || (event.target as HTMLElement).closest('article')) return
  const element = viewport.value
  if (!element) return
  stopPan()
  event.preventDefault()
  const x = event.clientX, y = event.clientY, left = element.scrollLeft, top = element.scrollTop
  const move = (next: PointerEvent) => { element.scrollLeft = left - (next.clientX - x); element.scrollTop = top - (next.clientY - y) }
  stopPan = () => { window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', stopPan); window.removeEventListener('pointercancel', stopPan) }
  window.addEventListener('pointermove', move)
  window.addEventListener('pointerup', stopPan, { once: true })
  window.addEventListener('pointercancel', stopPan, { once: true })
}
onBeforeUnmount(() => stopPan())
</script>

<style scoped>
.runtime-canvas { height: 100%; overflow: auto; cursor: grab; background-color: var(--surface, #f8faf9); background-image: linear-gradient(#8b9b9420 1px, transparent 1px), linear-gradient(90deg, #8b9b9420 1px, transparent 1px); background-size: 20px 20px; }
.runtime-canvas__world { position: relative; transform-origin: 0 0; }
.runtime-canvas__links { position: absolute; inset: 0; pointer-events: none; overflow: visible; }
.runtime-canvas__links path { fill: none; stroke: var(--color-primary, #168667); stroke-width: 2; opacity: .65; }
.runtime-canvas__node, .runtime-canvas__note { position: absolute; border: 1px solid var(--border-color, #c5d4ce); border-radius: 10px; background: var(--surface, #fff); color: var(--text-primary, #17251f); box-shadow: 0 5px 16px #19382a12; cursor: default; }
.runtime-canvas__node.is-disabled { opacity: .5; }
.runtime-canvas__group { position: absolute; border: 1px dashed var(--border-color, #c5d4ce); border-radius: 12px; background: #829a8910; color: var(--text-secondary, #66776e); padding: 8px; pointer-events: none; }
.runtime-canvas__node header { box-sizing: border-box; height: 54px; padding: 10px 12px; border-bottom: 1px solid var(--border-color, #dbe3df); }
.runtime-canvas__node header strong, .runtime-canvas__node header small { display: block; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.runtime-canvas__node small { display: block; overflow-wrap: anywhere; color: var(--text-secondary, #6b7972); font-size: 11px; }
.runtime-canvas__ports { display: flex; justify-content: space-between; padding: 4px 8px; gap: 6px; font-size: 11px; color: var(--text-secondary, #66776e); }
.runtime-canvas__ports span { display: block; line-height: 22px; }
.runtime-canvas__ports > div:last-child { text-align: right; }
.runtime-canvas__parameters { padding: 6px 12px; font-size: 11px; }
.runtime-canvas__parameters pre { max-height: 180px; overflow: auto; white-space: pre-wrap; overflow-wrap: anywhere; }
.runtime-canvas__identity { padding: 4px 12px; }
.runtime-canvas__note { padding: 14px; background: #fff9e8; }
.runtime-canvas__note pre { white-space: pre-wrap; }
</style>
