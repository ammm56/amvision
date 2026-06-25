<template>
  <section class="workflow-graph-workbench" :class="`workflow-graph-workbench--${graphTheme}`">
    <header class="workflow-graph-toolbar">
      <div class="workflow-graph-toolbar__title">
        <RouterLink to="/workflows/apps" class="workflow-graph-toolbar__back">
          <ArrowLeft :size="16" />
          {{ t('workflowEditor.actions.backToApps') }}
        </RouterLink>
        <div>
          <h1>{{ editorTitle }}</h1>
        </div>
      </div>
      <div class="workflow-graph-toolbar__meta">
        <span>{{ t('workflowEditor.fields.nodeCount') }} {{ graphNodes.length }}</span>
        <span>{{ t('workflowEditor.fields.edgeCount') }} {{ graphLinks.length }}</span>
        <span v-if="workflowApp?.primaryRuntime?.observed_state">{{ workflowApp.primaryRuntime.observed_state }}</span>
        <StatusBadge v-if="lastPreviewRun" :tone="readPreviewRunBadgeTone(lastPreviewRun.state)">{{ formatPreviewRunStatusLabel(lastPreviewRun.state) }}</StatusBadge>
        <span v-if="toolbarStatusMessage">{{ toolbarStatusMessage }}</span>
      </div>
      <div class="workflow-graph-toolbar__actions">
        <Button variant="secondary" :disabled="loading" @click="loadPage">
          <RefreshCw :size="16" />
          {{ t('common.refresh') }}
        </Button>
        <Button variant="secondary" @click="toggleGraphTheme">
          <Sun v-if="graphTheme === 'dark'" :size="16" />
          <Moon v-else :size="16" />
          {{ graphTheme === 'dark' ? t('preferences.light') : t('preferences.dark') }}
        </Button>
        <Button variant="secondary" :disabled="previewDisabled" @click="runPreview">
          <Play :size="16" />
          {{ t('workflowEditor.actions.previewRun') }}
        </Button>
        <Button variant="primary" :disabled="saveDisabled" @click="saveCurrentWorkflowApp">
          <Save :size="16" />
          {{ t('workflowEditor.actions.saveWorkflowApp') }}
        </Button>
      </div>
    </header>

    <div
      ref="canvasRef"
      class="workflow-graph-stage"
      @mousedown="startStagePan"
      @wheel="handleStageWheel"
      @contextmenu.prevent="openStageContextMenu"
    >
      <InlineError v-if="errorMessage" class="workflow-graph-error" :message="errorMessage" />

      <div class="workflow-graph-world" :style="worldTransformStyle">
        <svg class="workflow-graph-links" aria-hidden="true">
          <path
            v-for="link in graphLinks"
            :key="`${link.edgeId}-hit-area`"
            class="workflow-graph-link-hit-area"
            :d="linkPath(link)"
            @click.stop="selectGraphLink(link)"
            @contextmenu.prevent.stop="openGraphLinkContextMenu($event, link)"
          />
          <path
            v-for="link in graphLinks"
            :key="link.edgeId"
            class="workflow-graph-link"
            :class="{ 'is-selected': isGraphLinkSelected(link), 'workflow-graph-link--boundary': link.linkKind !== 'edge' }"
            :d="linkPath(link)"
            @click.stop="selectGraphLink(link)"
            @contextmenu.prevent.stop="openGraphLinkContextMenu($event, link)"
          />
          <circle
            v-for="marker in graphLinkMidpoints"
            :key="`${marker.edgeId}-midpoint`"
            class="workflow-graph-link-midpoint"
            :class="{ 'is-selected': isGraphLinkSelected(marker.link) }"
            :cx="marker.x"
            :cy="marker.y"
            r="4.5"
            @click.stop="selectGraphLink(marker.link)"
            @contextmenu.prevent.stop="openGraphLinkContextMenu($event, marker.link)"
          />
          <circle
            v-for="handle in selectedEdgeReconnectHandles"
            :key="handle.key"
            class="workflow-graph-link-handle workflow-graph-link-handle--center"
            :cx="handle.x"
            :cy="handle.y"
            r="6"
            @mousedown.stop.prevent="startEdgeTargetReconnect($event, handle.edgeId)"
          >
            <title>拖到新的输入端口重新连接</title>
          </circle>
          <path v-if="connectionDraft" class="workflow-graph-link workflow-graph-link--draft" :d="draftLinkPath" />
        </svg>

        <div
          v-for="boundary in appBoundaryNodes"
          :key="boundary.id"
          role="button"
          tabindex="0"
          class="workflow-graph-boundary-node"
          :class="[`workflow-graph-boundary-node--${boundary.kind}`, { 'is-selected': selectedBoundaryKind === boundary.kind, 'is-dragging': boundaryDragState?.boundaryKind === boundary.kind }]"
          :style="{ left: `${boundary.x}px`, top: `${boundary.y}px`, width: `${boundary.width}px`, height: `${boundaryNodeHeight(boundary)}px` }"
          @mousedown.stop="startBoundaryDrag($event, boundary)"
          @click.stop="selectApplicationBoundary(boundary.kind)"
          @contextmenu.prevent.stop="openBoundaryContextMenu($event, boundary)"
        >
          <div class="workflow-graph-boundary-node__header">
            <span class="workflow-graph-boundary-node__title">{{ boundary.title }}</span>
            <span class="workflow-graph-boundary-node__type">{{ boundary.description }}</span>
          </div>
          <div class="workflow-graph-boundary-node__ports">
            <span
              v-for="binding in boundary.bindings"
              :key="`${boundary.id}-${binding.binding_id}`"
              class="workflow-graph-port workflow-graph-boundary-port"
              :class="[
                `workflow-graph-port--${boundary.portDirection}`,
                { 'is-connected': isBoundaryPortConnected(boundary.kind, binding), 'is-selected-endpoint': selectedBoundaryKind === boundary.kind },
              ]"
              :data-node-id="boundary.id"
              :data-port-name="binding.binding_id"
              :data-payload-type-id="getBindingPayloadTypeId(binding)"
              :data-port-direction="boundary.portDirection"
              @mousedown.stop="startBoundaryPortConnection($event, boundary, binding)"
              @click.stop="selectBoundaryBinding(boundary.kind, binding)"
              @contextmenu.prevent.stop="openBoundaryPortContextMenu($event, boundary, binding)"
            >
              <span v-if="boundary.portDirection === 'input'" class="workflow-graph-port__dot" aria-hidden="true" />
              <span class="workflow-graph-port__label">
                <strong>{{ binding.binding_id }}</strong>
                <small>{{ getBindingPayloadTypeId(binding) || 'unknown' }}</small>
              </span>
              <span v-if="boundary.portDirection === 'output'" class="workflow-graph-port__dot" aria-hidden="true" />
            </span>
          </div>
        </div>

        <div
          v-for="node in graphNodes"
          :key="node.node.node_id"
          role="button"
          tabindex="0"
          class="workflow-graph-node"
          :class="{ 'is-selected': selectedNodeId === node.node.node_id, 'is-runtime-failed': lastPreviewFailureNodeId === node.node.node_id }"
          :style="{ left: `${node.x}px`, top: `${node.y}px`, width: `${node.width}px`, height: `${nodeVisualHeight(node)}px` }"
          @mousedown.stop="startNodeDrag($event, node)"
          @click.stop="handleNodeClick(node.node.node_id)"
          @contextmenu.prevent.stop="openNodeContextMenu($event, node)"
        >
          <span class="workflow-graph-node__title">{{ readGraphNodeTitle(node) }}</span>
          <span class="workflow-graph-node__type">{{ node.definition?.category || node.node.node_type_id }}</span>
          <div class="workflow-graph-node__ports">
            <div v-for="row in nodePortRows(node)" :key="row.key" class="workflow-graph-node__port-row">
              <span
                v-if="row.input"
                class="workflow-graph-port workflow-graph-port--input"
                :class="{
                  'is-connected': isPortConnected(node.node.node_id, row.input.name, 'input'),
                  'is-selected-endpoint': isSelectedEdgeEndpoint(node.node.node_id, row.input.name, 'input'),
                  'is-draft-anchor': isDraftAnchorPort(node.node.node_id, row.input.name, 'input'),
                }"
                :data-node-id="node.node.node_id"
                :data-port-name="row.input.name"
                :data-payload-type-id="row.input.payload_type_id"
                data-port-direction="input"
                @mousedown.stop.prevent="startPortConnection($event, node, row.input, 'input')"
                @click.stop="selectPortEndpoint(node, row.input, 'input')"
                @contextmenu.prevent.stop="openPortContextMenu($event, node, row.input, 'input')"
              >
                <span class="workflow-graph-port__dot" aria-hidden="true" />
                <span class="workflow-graph-port__label">{{ readNodePortLabel(row.input) }}</span>
              </span>
              <span v-else class="workflow-graph-port workflow-graph-port--placeholder" />
              <span
                v-if="row.output"
                class="workflow-graph-port workflow-graph-port--output"
                :class="{
                  'is-connected': isPortConnected(node.node.node_id, row.output.name, 'output'),
                  'is-selected-endpoint': isSelectedEdgeEndpoint(node.node.node_id, row.output.name, 'output'),
                  'is-draft-anchor': isDraftAnchorPort(node.node.node_id, row.output.name, 'output'),
                }"
                :data-node-id="node.node.node_id"
                :data-port-name="row.output.name"
                :data-payload-type-id="row.output.payload_type_id"
                data-port-direction="output"
                @mousedown.stop.prevent="startPortConnection($event, node, row.output, 'output')"
                @click.stop="selectPortEndpoint(node, row.output, 'output')"
                @contextmenu.prevent.stop="openPortContextMenu($event, node, row.output, 'output')"
              >
                <span class="workflow-graph-port__label">{{ readNodePortLabel(row.output) }}</span>
                <span class="workflow-graph-port__dot" aria-hidden="true" />
              </span>
              <span v-else class="workflow-graph-port workflow-graph-port--placeholder" />
            </div>
          </div>
          <WorkflowNodeParameterWidgets
            v-if="nodeParameterFieldsForNode(node).length"
            :node="node"
            :fields="nodeParameterFieldsForNode(node)"
            :read-label="readNodeParameterLabel"
            :read-enum-value="readNodeParameterEnumIndex"
            :read-enum-options="nodeParameterEnumOptions"
            :is-boolean="isBooleanParameter"
            :read-boolean-value="readNodeParameterBooleanValue"
            :is-number="isNumberParameter"
            :read-text-value="readNodeParameterTextValue"
            :is-string="isStringParameter"
            :is-json="isJsonParameter"
            :read-json-text-value="readNodeParameterJsonTextValue"
            :read-json-placeholder="nodeParameterJsonPlaceholder"
            @update-enum="updateNodeParameterFromEnumValue"
            @update-checkbox="updateNodeParameterFromCheckboxEvent"
            @update-number="updateNodeParameterFromNumberEvent"
            @update-text="updateNodeParameterFromTextEvent"
            @update-json-draft="updateNodeParameterJsonDraft"
            @commit-json-draft="commitNodeParameterJsonDraft"
          />
          <WorkflowNodePreviewDisplay
            v-if="previewNodeDisplays[node.node.node_id]"
            :display="previewNodeDisplays[node.node.node_id]"
            :tooltip="readPreviewNodeDisplayTooltip(previewNodeDisplays[node.node.node_id])"
            :fallback-title="readGraphNodeTitle(node)"
            @open-display="openPreviewDisplayViewer"
            @open-image="openImageViewer"
          />
        </div>
      </div>

      <aside v-if="!inspectorCollapsed" class="workflow-graph-floating-panel workflow-graph-inspector-panel" @mousedown.stop @contextmenu.stop>
        <div class="workflow-graph-panel__header">
          <div>
            <h2>{{ t('workflowEditor.editor.inspectorTitle') }}</h2>
          </div>
          <div class="workflow-graph-panel__tools">
            <button
              type="button"
              class="workflow-graph-panel__icon-button"
              :title="t('workflowEditor.editor.hideInspector')"
              :aria-label="t('workflowEditor.editor.hideInspector')"
              @click="collapseInspector"
            >
              <PanelRightClose :size="15" />
            </button>
          </div>
        </div>
        <WorkflowNewAppDraftPanel
          v-if="showNewAppDraftPanel"
          :draft="newWorkflowAppDraft"
          :save-blocker="newWorkflowAppSaveBlocker"
          @update-display-name="updateNewWorkflowDraftField('displayName', $event)"
          @update-application-id="updateNewWorkflowDraftField('applicationId', $event)"
          @update-graph-id="updateNewWorkflowDraftField('graphId', $event)"
          @update-graph-version="updateNewWorkflowDraftField('graphVersion', $event)"
          @update-description="updateNewWorkflowDraftField('description', $event)"
          @normalize-application-id="normalizeNewWorkflowApplicationId"
          @normalize-graph-id="normalizeNewWorkflowGraphId"
          @normalize-graph-version="normalizeNewWorkflowGraphVersion"
        />
        <WorkflowAppContractPanel
          v-if="showAppContractPanel"
          :input-bindings="appInputBindings"
          :output-bindings="appOutputBindings"
          :get-payload-type-id="getBindingPayloadTypeId"
          @add-request-image-ref="addRequestImageRefInput"
          @add-request-image-base64="addRequestImageBase64Input"
        />
        <WorkflowNodeDetailPanel
          v-if="inspectorDetail.kind === 'node'"
          :node="inspectorDetail.node"
          :read-title="readGraphNodeTitle"
        />
        <WorkflowEdgeDetailPanel v-else-if="inspectorDetail.kind === 'edge'" :edge="inspectorDetail.edge" @delete-edge="deleteSelectedEdge" />
        <WorkflowPublicBindingEditorPanel
          v-else-if="inspectorDetail.kind === 'boundary'"
          :title="inspectorDetail.title"
          :bindings="inspectorDetail.bindings"
          :read-endpoint-text="bindingEndpointText"
          :read-display-name="bindingDisplayName"
          :read-kind-options="bindingKindSelectOptions"
          :get-payload-type-id="getBindingPayloadTypeId"
          @update-binding-id="updateBindingIdFromEvent"
          @update-display-name="updateBindingDisplayNameFromEvent"
          @update-kind="updateBindingKindFromValue"
          @update-required="updateBindingRequiredFromEvent"
          @delete-binding="deleteApplicationBinding"
        />
        <WorkflowApplicationSummaryPanel
          v-else-if="inspectorDetail.kind === 'application'"
          :application-id="inspectorDetail.applicationId"
          :template-input-text="inspectorDetail.templateInputText"
          :template-output-text="inspectorDetail.templateOutputText"
          :empty-text="t('common.noValue')"
          :preview-run-text="inspectorDetail.previewRunText"
        />
        <EmptyState v-else :title="t('workflowEditor.editor.emptyInspectorTitle')" :description="t('workflowEditor.editor.emptyInspectorDescription')" />

        <WorkflowPreviewInputPanel
          v-if="showAppContractPanel"
          :bindings="previewInputBindings"
          :states="previewInputState"
          :blocking-messages="previewBlockingMessages"
          :help-text="previewHelpText"
          :image-ref-transport-kind-options="imageRefTransportKindOptions"
          :get-payload-type-id="getBindingPayloadTypeId"
          :read-binding-help-text="previewBindingHelpText"
          @add-value-field="addPreviewValueField"
          @remove-value-field="removePreviewValueField"
          @set-image-ref-transport-kind="setPreviewImageRefTransportKind"
        />
        <WorkflowPreviewRunResultPanel
          v-if="lastPreviewRun"
          :preview-run="lastPreviewRun"
          :badge-tone="readPreviewRunBadgeTone(lastPreviewRun.state)"
          :status-label="formatPreviewRunStatusLabel(lastPreviewRun.state)"
          :created-at-text="formatSystemDateTime(lastPreviewRun.created_at)"
          :failure-message="lastPreviewFailureMessage"
          :failure-node-label="lastPreviewFailureNodeLabel"
          :failure-location="lastPreviewFailureLocation"
          :failure-detail-message="lastPreviewFailureDetailMessage"
          :failure-details="lastPreviewFailureDetails"
          :failure-details-json="lastPreviewFailureDetailsJson"
          :http-response="lastPreviewHttpResponse"
          :http-response-body-value="lastPreviewHttpResponseBodyValue"
          :http-status="lastPreviewHttpStatus"
          :http-response-json="lastPreviewHttpResponseJson"
          :http-response-body-json="lastPreviewHttpResponseBodyJson"
          :has-node-displays="hasPreviewNodeDisplays"
          @open-json="openPreviewJsonViewer"
        />
      </aside>
      <button
        v-else
        type="button"
        class="workflow-graph-inspector-toggle"
        :title="t('workflowEditor.editor.showInspector')"
        :aria-label="t('workflowEditor.editor.showInspector')"
        @mousedown.stop
        @click.stop="expandInspector"
      >
        <PanelRightOpen :size="16" />
      </button>

      <WorkflowGraphMinimap
        :visible="minimapVisible"
        :nodes="minimapNodes"
        :viewport-style="minimapViewportStyle"
        :is-node-selected="isMinimapNodeSelected"
        @start-navigation="startMinimapNavigation"
        @toggle="toggleMinimap"
      />

      <WorkflowGraphContextMenu
        v-if="contextMenu"
        :context-menu="contextMenu"
        :menu-style="contextMenuStyle"
        :minimap-visible="minimapVisible"
        :graph-theme="graphTheme"
        :save-disabled="saveDisabled"
        :preview-disabled="previewDisabled"
        :add-node-label="t('workflowEditor.nodePicker.addNode')"
        :light-label="t('preferences.light')"
        :dark-label="t('preferences.dark')"
        :save-label="t('workflowEditor.actions.saveWorkflowApp')"
        :preview-label="t('workflowEditor.actions.previewRun')"
        @open-node-picker="openNodePickerFromContextMenu"
        @expose-app-input="exposeContextPortAsAppInput"
        @expose-app-output="exposeContextPortAsAppOutput"
        @delete-binding="deleteContextApplicationBinding"
        @delete-node="deleteSelectedNode"
        @delete-edge="deleteSelectedEdge"
        @reset-boundary-position="resetContextBoundaryPosition"
        @fit-view="fitView"
        @reset-view="resetView"
        @toggle-minimap="toggleMinimap"
        @toggle-theme="toggleGraphTheme"
        @save="saveCurrentWorkflowApp"
        @preview="runPreview"
      />

      <WorkflowNodePicker
        v-if="nodePicker"
        :open="Boolean(nodePicker)"
        :x="nodePicker.x"
        :y="nodePicker.y"
        :definitions="nodePickerDefinitions"
        :mode="nodePicker.mode"
        :title="nodePickerTitle"
        :required-port-direction="nodePickerRequiredPortDirection"
        :required-payload-type-id="nodePickerRequiredPayloadTypeId"
        @select="selectNodeFromPicker"
        @close="closeNodePicker"
      />

      <div v-if="!loading && graphNodes.length === 0" class="workflow-graph-empty">
        <Workflow :size="42" />
        <strong>{{ t('workflowEditor.editor.canvasPlaceholderTitle') }}</strong>
        <span>{{ isNewApp ? '右键画布添加节点，至少添加一个节点后可以首次保存应用。' : t('workflowEditor.editor.canvasPlaceholderDescription') }}</span>
      </div>
    </div>
    <ImageViewer :open="Boolean(activeImageViewer)" :image="activeImageViewer" @close="activeImageViewer = null" />
    <WorkflowPreviewTableViewer :open="Boolean(activePreviewTable)" :table="activePreviewTable" @close="activePreviewTable = null" />
    <WorkflowPreviewJsonViewer :open="Boolean(activePreviewJson)" :viewer="activePreviewJson" @close="activePreviewJson = null" />
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, shallowRef } from 'vue'
import { ArrowLeft, Moon, PanelRightClose, PanelRightOpen, Play, RefreshCw, Save, Sun, Workflow } from '@lucide/vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'

import { usePreferencesStore } from '@/app/stores/preferences.store'
import { useProjectStore } from '@/app/stores/project.store'
import type { SupportedLocale } from '@/platform/i18n'
import { formatSystemDateTime } from '@/shared/formatters/date-time'
import Button from '@/shared/ui/components/Button.vue'
import ImageViewer from '@/shared/ui/components/ImageViewer.vue'
import StatusBadge from '@/shared/ui/data-display/StatusBadge.vue'
import EmptyState from '@/shared/ui/feedback/EmptyState.vue'
import InlineError from '@/shared/ui/feedback/InlineError.vue'
import WorkflowGraphContextMenu from '../components/WorkflowGraphContextMenu.vue'
import WorkflowGraphMinimap from '../components/WorkflowGraphMinimap.vue'
import WorkflowAppContractPanel from '../components/WorkflowAppContractPanel.vue'
import WorkflowApplicationSummaryPanel from '../components/WorkflowApplicationSummaryPanel.vue'
import WorkflowEdgeDetailPanel from '../components/WorkflowEdgeDetailPanel.vue'
import WorkflowNewAppDraftPanel from '../components/WorkflowNewAppDraftPanel.vue'
import WorkflowNodeDetailPanel from '../components/WorkflowNodeDetailPanel.vue'
import WorkflowNodeParameterWidgets from '../components/WorkflowNodeParameterWidgets.vue'
import WorkflowNodePicker from '../components/WorkflowNodePicker.vue'
import WorkflowNodePreviewDisplay from '../components/WorkflowNodePreviewDisplay.vue'
import WorkflowPublicBindingEditorPanel from '../components/WorkflowPublicBindingEditorPanel.vue'
import WorkflowPreviewInputPanel from '../components/WorkflowPreviewInputPanel.vue'
import WorkflowPreviewRunResultPanel from '../components/WorkflowPreviewRunResultPanel.vue'
import WorkflowPreviewJsonViewer from '../components/WorkflowPreviewJsonViewer.vue'
import WorkflowPreviewTableViewer from '../components/WorkflowPreviewTableViewer.vue'
import { useWorkflowCanvasPan } from '../canvas/useWorkflowCanvasPan'
import { useWorkflowCanvasViewport } from '../canvas/useWorkflowCanvasViewport'
import { useWorkflowBoundaryDrag } from '../canvas/useWorkflowBoundaryDrag'
import { useWorkflowConnectionInteractions } from '../canvas/useWorkflowConnectionInteractions'
import { useWorkflowEdgeHandles } from '../canvas/useWorkflowEdgeHandles'
import { useWorkflowNodeDrag } from '../canvas/useWorkflowNodeDrag'
import { useWorkflowPortConnections } from '../canvas/useWorkflowPortConnections'
import type { WorkflowLiteGraphAdapter } from '../canvas/graph-engine/litegraph-adapter'
import { type WorkflowCanvasGraphSnapshot } from '../canvas/graph-engine/workflow-graph-conversion'
import { useWorkflowConnectionRules } from '../connections/useWorkflowConnectionRules'
import { useWorkflowContextMenu, type WorkflowContextMenuState } from '../context/useWorkflowContextMenu'
import { useWorkflowGraphGeometry, type WorkflowGraphLinkView } from '../geometry/useWorkflowGraphGeometry'
import { useWorkflowPreviewDisplays } from '../preview/useWorkflowPreviewDisplays'
import { previewImageRefTransportKindOptions, useWorkflowPreviewInputs } from '../preview/useWorkflowPreviewInputs'
import { formatPreviewRunStatusLabel, readPreviewRunBadgeTone, useWorkflowPreviewValidation } from '../preview/useWorkflowPreviewValidation'
import { useWorkflowDocumentLoader } from '../documents/useWorkflowDocumentLoader'
import { useWorkflowNewAppDraft } from '../documents/useWorkflowNewAppDraft'
import { useWorkflowInspectorPanel } from '../panels/useWorkflowInspectorPanel'
import { useWorkflowInspectorViewModel } from '../panels/useWorkflowInspectorViewModel'
import { useWorkflowEditorKeyboard } from '../shell/useWorkflowEditorKeyboard'
import { useWorkflowGraphTheme } from '../shell/useWorkflowGraphTheme'
import { useWorkflowPublicBindings, type WorkflowBoundaryKind } from '../bindings/useWorkflowPublicBindings'
import { useWorkflowBindingEditorActions } from '../bindings/useWorkflowBindingEditorActions'
import { useWorkflowBoundaryNodes, type WorkflowBoundaryNodeView } from '../bindings/useWorkflowBoundaryNodes'
import { useWorkflowGraphDeletion } from '../graph/useWorkflowGraphDeletion'
import { useWorkflowRequestImageInputs } from '../graph/useWorkflowRequestImageInputs'
import { useWorkflowGraphNodeViews, type WorkflowGraphNodeView } from '../nodes/useWorkflowGraphNodeViews'
import { useWorkflowNodePicker } from '../nodes/useWorkflowNodePicker'
import {
  buildInitialNodeParameters,
  useWorkflowNodeParameters,
  type WorkflowNodeParameterSelectValue,
} from '../parameters/useWorkflowNodeParameters'
import { useWorkflowPreflight } from '../validation/useWorkflowPreflight'
import { useWorkflowEditorActions } from '../actions/useWorkflowEditorActions'
import { useWorkflowSaveRunFeedback } from '../actions/useWorkflowSaveRunFeedback'
import { useWorkflowSaveRunOrchestration } from '../actions/useWorkflowSaveRunOrchestration'
import { useWorkflowSelectionState } from '../selection/useWorkflowSelectionState'
import { resolveNodeDefinitionDisplayName, resolveNodeParameterDisplayName, resolveNodePortDisplayName } from '../node-definition-localization'
import type { WorkflowAppDocument } from '../services/workflow-app.service'
import type { FlowApplication, FlowApplicationBinding, NodeParameterUiField, NodePortDefinition, WorkflowGraphEdge, WorkflowGraphInput, WorkflowGraphNode, WorkflowGraphOutput, WorkflowNodeCatalogResponse } from '../types'

type AppBoundaryKind = WorkflowBoundaryKind
type SelectValue = WorkflowNodeParameterSelectValue
type GraphLinkView = WorkflowGraphLinkView
type GraphNodeView = WorkflowGraphNodeView

type ContextMenuState = WorkflowContextMenuState<AppBoundaryKind>

type AppBoundaryNodeView = WorkflowBoundaryNodeView

interface NodePortRowView {
  key: string
  input: NodePortDefinition | null
  output: NodePortDefinition | null
}

const { t, locale } = useI18n()
const route = useRoute()
const router = useRouter()
const preferencesStore = usePreferencesStore()
const projectStore = useProjectStore()
const {
  saving,
  previewing,
  errorMessage,
  statusMessage,
  lastPreviewRun,
  saveWorkflowDocument,
  runWorkflowPreview,
  clearActionMessages,
  setActionError,
  setActionStatus,
  resetPreviewRun,
} = useWorkflowEditorActions()

const currentLocale = computed<SupportedLocale>(() => {
  const value = typeof locale.value === 'string' ? locale.value : 'en-US'
  return value === 'zh-CN' || value === 'en-US' || value === 'ja-JP' || value === 'ko-KR' ? value : 'en-US'
})

const loading = ref(false)
const nodeCatalog = ref<WorkflowNodeCatalogResponse | null>(null)
const workflowApp = ref<WorkflowAppDocument | null>(null)
const graphNodes = ref<GraphNodeView[]>([])
const graphEdges = ref<WorkflowGraphEdge[]>([])
const templateInputs = ref<WorkflowGraphInput[]>([])
const templateOutputs = ref<WorkflowGraphOutput[]>([])
const contextMenu = ref<ContextMenuState | null>(null)
const complexParameterDrafts = ref<Record<string, string>>({})
const canvasRef = ref<HTMLElement | null>(null)
const {
  inspectorCollapsed,
  collapseInspector,
  expandInspector,
} = useWorkflowInspectorPanel()
const {
  graphTheme,
  toggleGraphTheme,
} = useWorkflowGraphTheme({
  readTheme: () => preferencesStore.theme,
  setTheme: (theme) => {
    preferencesStore.setTheme(theme)
  },
  lightTheme: 'light',
  darkTheme: 'dark',
  clearContextMenu: () => {
    contextMenu.value = null
  },
})
const {
  nodeDefinitionsById,
  nodePickerDefinitions,
  buildDefaultGraphNodeWidth,
  buildGraphNodeView,
  buildGraphNodeViews,
} = useWorkflowGraphNodeViews({
  nodeCatalog,
  graphEdges,
})
const {
  minimapVisible,
  viewportX,
  viewportY,
  viewportScale,
  stageSize,
  worldTransformStyle,
  minimapNodes,
  minimapViewportStyle,
  screenToWorld,
  handleStageWheel,
  fitView,
  focusGraphNode,
  resetView,
  toggleMinimap,
  startMinimapNavigation,
  stopMinimapNavigation,
  updateStageSize,
} = useWorkflowCanvasViewport<GraphNodeView, AppBoundaryNodeView>({
  canvasRef,
  graphNodes,
  readBoundaryNodes: () => appBoundaryNodes.value,
  readNodeId: (node) => node.node.node_id,
  readNodeHeight: (node) => nodeVisualHeight(node),
  readBoundaryHeight: (boundary) => boundaryNodeHeight(boundary),
  selectNode: (nodeId) => {
    selectNode(nodeId)
  },
  shouldIgnoreWheelTarget: shouldIgnoreStageWheelTarget,
  clearTransientUi: () => {
    contextMenu.value = null
    nodePicker.value = null
  },
})
const {
  nodePicker,
  nodePickerTitle,
  nodePickerRequiredPortDirection,
  nodePickerRequiredPayloadTypeId,
  addGraphNode,
  openNodePickerFromContextMenu,
  openNodePickerFromConnectionDraft,
  closeNodePicker,
  selectNodeFromPicker,
} = useWorkflowNodePicker<GraphNodeView, ContextMenuState>({
  graphNodes,
  contextMenu,
  createNodeView: ({ definition, nodeId, x, y, index }) => {
    const node: WorkflowGraphNode = {
      node_id: nodeId,
      node_type_id: definition.node_type_id,
      parameters: buildInitialNodeParameters(definition),
      ui_state: { x, y, width: buildDefaultGraphNodeWidth(definition) },
      metadata: {},
    }
    return buildGraphNodeView(node, index, new Map([[nodeId, { x, y }]]))
  },
  screenToWorld,
  getConnectionDraftPayloadTypeId: (draft) => getConnectionDraftPayloadTypeId(draft),
  connectConnectionDraftToNewNode: (draft, graphNode) => connectConnectionDraftToNewNode(draft, graphNode),
  setSelection: (selection) => {
    setSelection(selection)
  },
  setStatusMessage: (message) => {
    statusMessage.value = message
  },
  setErrorMessage: (message) => {
    errorMessage.value = message
  },
  readAddNodeTitle: () => t('workflowEditor.nodePicker.addNode'),
  readSelectAndConnectTitle: () => t('workflowEditor.nodePicker.selectAndConnect'),
})
const { startStagePan, stopStagePan } = useWorkflowCanvasPan({
  viewportX,
  viewportY,
  shouldIgnorePointerTarget: shouldIgnoreStagePointer,
  beforeStart: () => {
    contextMenu.value = null
    nodePicker.value = null
  },
})
const {
  previewNodeDisplays,
  activeImageViewer,
  activePreviewTable,
  activePreviewJson,
  hasPreviewNodeDisplays,
  refreshPreviewNodeDisplays,
  revokePreviewImageObjectUrls,
  getPreviewNodeDisplay,
  readPreviewNodeDisplayTooltip,
  openPreviewDisplayViewer,
  openImageViewer,
  openPreviewJsonViewer,
} = useWorkflowPreviewDisplays()
const {
  previewInputState,
  hasPreviewBindingValue,
  initializePreviewInputs,
  setPreviewInputStateForBinding,
  renamePreviewInputState,
  removePreviewInputState,
  removePreviewInputStates,
  addPreviewValueField,
  removePreviewValueField,
  setPreviewImageRefTransportKind: updatePreviewImageRefTransportKind,
  buildPreviewInputBindings: buildPreviewInputBindingsPayload,
} = useWorkflowPreviewInputs({ getBindingPayloadTypeId })
const {
  applicationBindingsDraft,
  boundaryPositions,
  appInputBindings,
  appOutputBindings,
  templateInputById,
  templateOutputById,
  initializePublicBindings,
  writeBoundaryPositionsToMetadata,
  readTemplatePortForBinding,
  getBindingPayloadTypeId: readPublicBindingPayloadTypeId,
  bindingDisplayName,
  bindingKindSelectOptions,
  renameApplicationBinding,
  setBindingDisplayName,
  updateApplicationBindingRequired,
  deleteApplicationBinding: deletePublicApplicationBinding,
  resetBoundaryPosition,
} = useWorkflowPublicBindings({
  templateInputs,
  templateOutputs,
  renamePreviewInputState,
  removePreviewInputState,
})
const {
  selectedNodeId,
  selectedEdgeId,
  selectedBoundaryKind,
  selectedNode,
  selectedEdge,
  readSelection,
  setSelection,
  clearTransientUi,
  selectNode,
  handleNodeClick,
  suppressNodeClickOnce,
  selectEdge,
  selectGraphLink,
  isGraphLinkSelected,
  selectApplicationBoundary,
  restoreSelectionAfterGraphRefresh,
} = useWorkflowSelectionState<GraphNodeView>({
  graphNodes,
  graphEdges,
  readNodeId: (node) => node.node.node_id,
  clearConnectionDraft: () => {
    connectionDraft.value = null
  },
  clearContextMenu: () => {
    contextMenu.value = null
  },
  clearNodePicker: () => {
    nodePicker.value = null
  },
})
const {
  bindingEndpointText,
  updateBindingIdFromEvent,
  updateBindingDisplayNameFromEvent,
  updateBindingKindFromValue,
  updateBindingRequiredFromEvent,
  deleteApplicationBinding,
  deleteContextApplicationBinding,
  resetContextBoundaryPosition,
} = useWorkflowBindingEditorActions({
  applicationBindingsDraft,
  selectedBoundaryKind,
  contextMenu,
  nodePicker,
  readTemplatePortForBinding,
  renameApplicationBinding,
  setBindingDisplayName,
  updateApplicationBindingRequired,
  deletePublicApplicationBinding,
  resetBoundaryPosition,
  selectApplicationBoundary,
  setStatusMessage: (message) => {
    statusMessage.value = message
  },
  setErrorMessage: (message) => {
    errorMessage.value = message
  },
})
const {
  appEntryBoundaryId,
  appResultBoundaryId,
  appBoundaryNodes,
  selectedBoundaryBindings,
  selectedBoundaryTitle,
  boundaryNodeHeight,
  boundaryPortY,
  boundaryPortX,
  isBoundaryPortConnected,
} = useWorkflowBoundaryNodes({
  graphNodes,
  selectedBoundaryKind,
  boundaryPositions,
  appInputBindings,
  appOutputBindings,
  templateInputById,
  templateOutputById,
})
const {
  portsCanConnect,
  findInputEdge,
  findOutputEdge,
  getConnectionDraftPayloadTypeId,
  connectConnectionDraftToNewNode,
  connectDraftToPort,
  connectOutputToInput,
} = useWorkflowConnectionRules({
  graphNodes,
  graphEdges,
  templateInputs,
  templateOutputs,
  appInputBindings,
  appOutputBindings,
  templateInputById,
  templateOutputById,
  appEntryBoundaryId,
  appResultBoundaryId,
  getBindingPayloadTypeId,
  setPreviewInputStateForBinding,
  setSelection,
  selectApplicationBoundary,
  setStatusMessage: (message) => {
    statusMessage.value = message
  },
  setErrorMessage: (message) => {
    errorMessage.value = message
  },
})
const {
  deleteGraphNode,
  deleteGraphEdge,
} = useWorkflowGraphDeletion({
  graphNodes,
  graphEdges,
  templateInputs,
  templateOutputs,
  applicationBindingsDraft,
  removePreviewInputStates,
  setSelection,
  clearTransientUi,
  setStatusMessage: (message) => {
    statusMessage.value = message
  },
})
const {
  contextMenuStyle,
  clearContextMenu,
  openGraphLinkContextMenu,
  selectPortEndpoint,
  exposeContextPortAsAppInput,
  exposeContextPortAsAppOutput,
  exposeNodeInputAsAppInput,
  deleteSelectedNode,
  deleteSelectedEdge,
  openNodeContextMenu,
  openPortContextMenu,
  openBoundaryContextMenu,
  openBoundaryPortContextMenu,
  openStageContextMenu,
} = useWorkflowContextMenu<GraphNodeView, AppBoundaryNodeView, GraphLinkView, AppBoundaryKind>({
  workflowApp,
  graphNodes,
  graphEdges,
  templateInputs,
  templateOutputs,
  applicationBindingsDraft,
  contextMenu,
  nodePicker,
  screenToWorld,
  findInputEdge,
  findOutputEdge,
  readSelectedNodeId: () => selectedNodeId.value,
  readSelectedEdgeId: () => selectedEdgeId.value,
  setPreviewInputStateForBinding,
  setSelection,
  selectNode,
  selectEdge,
  selectApplicationBoundary,
  deleteGraphNode,
  deleteGraphEdge,
  shouldIgnoreStagePointer,
  setStatusMessage: (message) => {
    statusMessage.value = message
  },
  setErrorMessage: (message) => {
    errorMessage.value = message
  },
})
const {
  connectionDraft,
  startPortConnectionDraft,
  stopPortConnection,
} = useWorkflowPortConnections({
  screenToWorld,
  connectDraftToPort,
  openNodePickerFromConnectionDraft,
  suppressNodeClickOnce,
  clearNodePicker: () => {
    nodePicker.value = null
  },
})
const {
  startNodeDrag,
  stopNodeDrag,
} = useWorkflowNodeDrag<GraphNodeView>({
  graphNodes,
  connectionDraft,
  screenToWorld,
  selectNode,
})
const {
  boundaryDragState,
  startBoundaryDrag,
  stopBoundaryDrag,
} = useWorkflowBoundaryDrag<AppBoundaryKind>({
  screenToWorld,
  canStart: () => !connectionDraft.value,
  onStart: (boundaryKind) => {
    selectApplicationBoundary(boundaryKind)
  },
  updateBoundaryPosition: (boundaryKind, position) => {
    boundaryPositions.value = {
      ...boundaryPositions.value,
      [boundaryKind]: position,
    }
  },
})
const liteGraphAdapter = shallowRef<WorkflowLiteGraphAdapter | null>(null)
let resizeObserver: ResizeObserver | null = null

const graphNodeHeaderHeight = 60
const graphPortRowHeight = 30
const graphPortInsetX = 18
const graphNodePreviewFrameHeight = 28
const graphNodePreviewImageHeight = 140
const graphNodePreviewDataHeight = 176
const graphNodePreviewGalleryColumns = 2
const graphNodePreviewGalleryItemHeight = 72
const graphNodePreviewGalleryGap = 6
const imageRefTransportKindOptions = previewImageRefTransportKindOptions
const graphNodeWidgetRowHeight = 34

const selectedProjectId = computed(() => projectStore.selectedProjectId)
const routeApplicationId = computed(() => (typeof route.params.applicationId === 'string' ? route.params.applicationId : ''))
const isNewApp = computed(() => route.path.endsWith('/new'))
const {
  showNewAppDraftPanel,
  showAppContractPanel,
  inspectorDetail,
} = useWorkflowInspectorViewModel<GraphNodeView>({
  workflowApp,
  isNewApp,
  selectedNode,
  selectedEdge,
  selectedBoundaryKind,
  selectedBoundaryTitle,
  selectedBoundaryBindings,
  lastPreviewRun,
})
const {
  newWorkflowAppDraft,
  newWorkflowAppSaveBlocker,
  resetNewWorkflowAppDraft,
  updateNewWorkflowDraftField,
  normalizeNewWorkflowApplicationId,
  normalizeNewWorkflowGraphId,
  normalizeNewWorkflowGraphVersion,
  readNewWorkflowAppSaveBlocker,
  createLocalWorkflowAppDraft,
  applyNewWorkflowTemplateSettings,
  buildNewWorkflowApplicationPatch,
} = useWorkflowNewAppDraft({
  isNewApp,
  selectedProjectId,
  readNodeCount: () => graphNodes.value.length,
})
const {
  runWorkflowPreflight,
  applyWorkflowValidationIssue,
} = useWorkflowPreflight({
  graphNodes,
  graphEdges,
  nodeDefinitionsById,
  portsCanConnect,
  focusGraphNode,
  setSelection,
  clearTransientUi,
  setErrorMessage: (message) => {
    errorMessage.value = message
  },
  setStatusMessage: (message) => {
    statusMessage.value = message
  },
})
const {
  nodeParameterFieldsForNode,
  isJsonParameter,
  isStringParameter,
  isNumberParameter,
  isBooleanParameter,
  readNodeParameterTextValue,
  readNodeParameterBooleanValue,
  readNodeParameterEnumIndex,
  nodeParameterEnumOptions,
  updateNodeParameterFromTextEvent,
  updateNodeParameterFromNumberEvent,
  updateNodeParameterFromCheckboxEvent,
  updateNodeParameterFromEnumValue,
  readNodeParameterJsonTextValue,
  updateNodeParameterJsonDraft,
  commitNodeParameterJsonDraft,
  nodeParameterJsonPlaceholder,
} = useWorkflowNodeParameters<GraphNodeView>({
  complexParameterDrafts,
  readNodeTitle: readGraphNodeTitle,
  readParameterLabel: readNodeParameterLabel,
  setStatusMessage: (message) => {
    statusMessage.value = message
  },
  setErrorMessage: (message) => {
    errorMessage.value = message
  },
})
const editorTitle = computed(() => isNewApp.value ? newWorkflowAppDraft.value.displayName || t('workflowEditor.editor.newTitle') : workflowApp.value?.applicationDocument.application.display_name || routeApplicationId.value)
const saveDisabled = computed(() => saving.value || !workflowApp.value || Boolean(newWorkflowAppSaveBlocker.value))
const previewDisabled = computed(() => previewing.value || !workflowApp.value || isNewApp.value || Boolean(newWorkflowAppSaveBlocker.value))
const {
  graphLinks,
  draftLinkPath,
  nodeVisualHeight,
  portX,
  portY,
  isPortConnected,
  linkPath,
  linkPointAt,
} = useWorkflowGraphGeometry<GraphNodeView>({
  graphNodes,
  graphEdges,
  templateInputs,
  templateOutputs,
  appBoundaryNodes,
  appInputBindings,
  appOutputBindings,
  templateInputById,
  templateOutputById,
  connectionDraft,
  readPreviewDisplay: getPreviewNodeDisplay,
  readParameterFields: nodeParameterFieldsForNode,
  isJsonParameter,
  boundaryPortX,
  boundaryPortY,
  layout: {
    nodeHeaderHeight: graphNodeHeaderHeight,
    portRowHeight: graphPortRowHeight,
    portInsetX: graphPortInsetX,
    nodePreviewFrameHeight: graphNodePreviewFrameHeight,
    nodePreviewImageHeight: graphNodePreviewImageHeight,
    nodePreviewDataHeight: graphNodePreviewDataHeight,
    nodePreviewGalleryColumns: graphNodePreviewGalleryColumns,
    nodePreviewGalleryItemHeight: graphNodePreviewGalleryItemHeight,
    nodePreviewGalleryGap: graphNodePreviewGalleryGap,
    nodeWidgetRowHeight: graphNodeWidgetRowHeight,
  },
  clampNumber,
})
const {
  graphLinkMidpoints,
  selectedEdgeReconnectHandles,
} = useWorkflowEdgeHandles({
  graphLinks,
  selectedEdgeId,
  linkPointAt,
})
const {
  isSelectedEdgeEndpoint,
  isDraftAnchorPort,
  startPortConnection,
  startBoundaryPortConnection,
  startEdgeTargetReconnect,
} = useWorkflowConnectionInteractions<GraphNodeView>({
  graphNodes,
  graphLinks,
  selectedEdge,
  connectionDraft,
  portX,
  portY,
  boundaryPortX,
  boundaryPortY,
  findInputEdge,
  startPortConnectionDraft,
  selectNode,
  selectEdge,
  selectApplicationBoundary,
  clearErrorMessage: () => {
    errorMessage.value = null
  },
})
const {
  addRequestImageRefInput,
  addRequestImageBase64Input,
  normalizeLoadedRequestImageInputBindings,
} = useWorkflowRequestImageInputs<GraphNodeView>({
  workflowApp,
  graphNodes,
  graphEdges,
  appBoundaryNodes,
  appInputBindings,
  applicationBindingsDraft,
  nodeDefinitionsById,
  boundaryPositions,
  stageSize,
  viewportX,
  viewportY,
  viewportScale,
  addGraphNode,
  deleteGraphNode,
  exposeNodeInputAsAppInput,
  renameApplicationBinding,
  setBindingDisplayName,
  updateApplicationBindingRequired,
  connectOutputToInput,
  selectApplicationBoundary,
  setStatusMessage: (message) => {
    statusMessage.value = message
  },
  setErrorMessage: (message) => {
    errorMessage.value = message
  },
})
const { handleKeydown } = useWorkflowEditorKeyboard({
  selectedNodeId,
  selectedEdgeId,
  clearConnectionDraft: () => {
    connectionDraft.value = null
  },
  clearContextMenu: () => {
    contextMenu.value = null
  },
  clearErrorMessage: () => {
    errorMessage.value = null
  },
  deleteSelectedNode,
  deleteSelectedEdge,
})
const {
  refreshSavedWorkflowApp,
  loadPage,
} = useWorkflowDocumentLoader({
  loading,
  nodeCatalog,
  workflowApp,
  graphNodes,
  graphEdges,
  templateInputs,
  templateOutputs,
  applicationBindingsDraft,
  liteGraphAdapter,
  selectedProjectId,
  isNewApp,
  routeApplicationId,
  readLoadFailedMessage: () => t('workflowEditor.messages.loadFailed'),
  clearActionMessages,
  resetPreviewRun,
  resetNewWorkflowAppDraft,
  createLocalWorkflowAppDraft,
  initializePublicBindings,
  initializePreviewInputs,
  normalizeLoadedRequestImageInputBindings,
  readSelection,
  setSelection,
  restoreSelectionAfterGraphRefresh,
  buildGraphNodeViews,
  clearComplexParameterDrafts: () => {
    complexParameterDrafts.value = {}
  },
  revokePreviewImageObjectUrls,
  updateStageSize,
  fitView,
  setErrorMessage: (message) => {
    errorMessage.value = message
  },
})
const {
  applyWorkflowSaveFeedback,
  applyPreviewRunFeedback,
} = useWorkflowSaveRunFeedback({
  replaceRouteWithSavedApp: async (applicationId) => {
    await router.replace(`/workflows/graph/apps/${encodeURIComponent(applicationId)}`)
  },
  refreshSavedWorkflowApp,
  resetPreviewRun,
  revokePreviewImageObjectUrls,
  refreshPreviewNodeDisplays,
  focusGraphNode,
  setActionError,
  setActionStatus,
})
const {
  saveCurrentWorkflowApp,
  runPreview,
} = useWorkflowSaveRunOrchestration({
  workflowApp,
  isNewApp,
  selectedProjectId,
  readNewWorkflowAppSaveBlocker,
  buildCurrentTemplate,
  buildCurrentApplication,
  runWorkflowPreflight,
  applyWorkflowValidationIssue,
  buildPreviewInputBindings,
  saveWorkflowDocument,
  runWorkflowPreview,
  applyWorkflowSaveFeedback,
  applyPreviewRunFeedback,
  clearActionMessages,
  revokePreviewImageObjectUrls,
  setActionError,
  clearContextMenu,
})
const previewInputBindings = computed(() => appInputBindings.value)
const previewAlternativeImageBindingIds = computed(() => {
  const metadata = workflowApp.value?.applicationDocument.application.metadata ?? {}
  const configuredIds = [metadata.http_input_binding, metadata.trigger_source_input_binding]
    .filter((value): value is string => typeof value === 'string' && value.trim().length > 0)
  if (configuredIds.length >= 2) return configuredIds
  const imageInputIds = previewInputBindings.value
    .filter((binding) => ['image-base64.v1', 'image-ref.v1'].includes(getBindingPayloadTypeId(binding)))
    .map((binding) => binding.binding_id)
  return imageInputIds.length >= 2 ? imageInputIds : []
})
const {
  previewBlockingMessages,
  previewHelpText,
  lastPreviewHttpResponse,
  lastPreviewHttpStatus,
  lastPreviewHttpResponseJson,
  lastPreviewHttpResponseBodyJson,
  lastPreviewHttpResponseBodyValue,
  lastPreviewFailureDetails,
  lastPreviewFailureNodeId,
  lastPreviewFailureMessage,
  lastPreviewFailureDetailMessage,
  lastPreviewFailureNodeLabel,
  lastPreviewFailureLocation,
  lastPreviewFailureDetailsJson,
} = useWorkflowPreviewValidation({
  lastPreviewRun,
  previewInputBindings,
  previewAlternativeImageBindingIds,
  hasPreviewBindingValue,
})
const toolbarStatusMessage = computed(() => {
  const message = statusMessage.value?.trim()
  if (!message) return null
  if (lastPreviewRun.value && message === formatPreviewRunStatusLabel(lastPreviewRun.value.state)) return null
  return message
})

function selectBoundaryBinding(kind: 'entry' | 'result', binding: FlowApplicationBinding): void {
  selectApplicationBoundary(kind)
  statusMessage.value = `已选择 ${binding.binding_id}`
}

function getBindingPayloadTypeId(binding: FlowApplicationBinding): string {
  return readPublicBindingPayloadTypeId(binding)
}

function readGraphNodeTitle(node: GraphNodeView): string {
  return node.definition ? resolveNodeDefinitionDisplayName(node.definition, currentLocale.value) : node.title
}

function readNodePortLabel(port: NodePortDefinition): string {
  return resolveNodePortDisplayName(port, currentLocale.value) || port.name
}

function readNodeParameterLabel(field: NodeParameterUiField): string {
  return resolveNodeParameterDisplayName(field, currentLocale.value) || field.parameter_name
}

function nodePortRows(node: GraphNodeView): NodePortRowView[] {
  const rowCount = Math.max(node.inputs.length, node.outputs.length)
  return Array.from({ length: rowCount }, (_, index) => ({
    key: `${node.node.node_id}-port-row-${index}`,
    input: node.inputs[index] ?? null,
    output: node.outputs[index] ?? null,
  }))
}

function isMinimapNodeSelected(nodeId: string): boolean {
  if (selectedNodeId.value === nodeId) return true
  if (selectedBoundaryKind.value === 'entry') return nodeId === appEntryBoundaryId
  if (selectedBoundaryKind.value === 'result') return nodeId === appResultBoundaryId
  return false
}

function clampNumber(value: number, minValue: number, maxValue: number): number {
  return Math.min(maxValue, Math.max(minValue, value))
}

function setPreviewImageRefTransportKind(bindingId: string, value: SelectValue): void {
  updatePreviewImageRefTransportKind(bindingId, value)
}

function shouldIgnoreStagePointer(target: EventTarget | null): boolean {
  return target instanceof Element && Boolean(target.closest('.workflow-graph-node, .workflow-graph-boundary-node, .workflow-graph-floating-panel, .workflow-graph-minimap, .workflow-graph-minimap-toggle, .workflow-graph-context-menu, .workflow-node-picker, .workflow-graph-link, .workflow-graph-link-hit-area, .workflow-graph-link-handle, .workflow-graph-port'))
}

function shouldIgnoreStageWheelTarget(target: EventTarget | null): boolean {
  return target instanceof Element && Boolean(target.closest('input, textarea, select, button, .workflow-graph-floating-panel, .workflow-graph-minimap, .workflow-graph-minimap-toggle, .workflow-graph-context-menu, .workflow-node-picker, .image-viewer'))
}

function previewBindingHelpText(binding: FlowApplicationBinding): string {
  const payloadTypeId = getBindingPayloadTypeId(binding) || 'unknown'
  const requiredText = binding.required ? '必填输入' : '可选输入'
  if (payloadTypeId === 'image-base64.v1') return `${requiredText}。选择图片文件后会自动转换为 image-base64 payload。`
  if (payloadTypeId === 'image-ref.v1') return `${requiredText}。可填写 ObjectStore object_key，或填写运行内存 image_handle。`
  if (payloadTypeId === 'value.v1') return `${requiredText}。按字段名和值提交 value payload。`
  return `${requiredText}。payload type: ${payloadTypeId}。`
}

async function buildPreviewInputBindings(): Promise<Record<string, unknown> | null> {
  if (previewBlockingMessages.value.length > 0) {
    errorMessage.value = previewBlockingMessages.value.join('；')
    return null
  }
  return buildPreviewInputBindingsPayload(previewInputBindings.value)
}

function createCanvasSnapshot(): WorkflowCanvasGraphSnapshot {
  return {
    nodes: graphNodes.value.map((node) => ({
      node_id: node.node.node_id,
      node_type_id: node.node.node_type_id,
      x: node.x,
      y: node.y,
      width: node.width,
      parameters: { ...node.node.parameters },
      metadata: { ...node.node.metadata },
      ui_state: { ...node.node.ui_state, x: node.x, y: node.y, width: node.width },
    })),
    edges: graphEdges.value.map((edge) => ({ ...edge, metadata: { ...edge.metadata } })),
    template_inputs: templateInputs.value.map((input) => ({ ...input, metadata: { ...input.metadata } })),
    template_outputs: templateOutputs.value.map((output) => ({ ...output, metadata: { ...output.metadata } })),
  }
}

function buildCurrentTemplate() {
  const sourceTemplate = workflowApp.value?.graphDocument.template
  if (!sourceTemplate) return null
  const snapshot = createCanvasSnapshot()
  const template = liteGraphAdapter.value?.exportTemplate(sourceTemplate, snapshot) ?? sourceTemplate
  return applyNewWorkflowTemplateSettings(template)
}

function buildCurrentApplication(template: ReturnType<typeof buildCurrentTemplate>): FlowApplication | null {
  const sourceApplication = workflowApp.value?.applicationDocument.application
  if (!sourceApplication || !template) return null
  return {
    ...buildNewWorkflowApplicationPatch(sourceApplication, template),
    bindings: applicationBindingsDraft.value.map((binding) => ({
      ...binding,
      config: { ...binding.config },
      metadata: { ...binding.metadata },
    })),
    metadata: writeBoundaryPositionsToMetadata(sourceApplication.metadata),
  }
}

onMounted(() => {
  loadPage()
  window.addEventListener('keydown', handleKeydown)
  window.addEventListener('resize', updateStageSize)
  if (typeof ResizeObserver !== 'undefined' && canvasRef.value) {
    resizeObserver = new ResizeObserver(updateStageSize)
    resizeObserver.observe(canvasRef.value)
  }
})

onUnmounted(() => {
  stopNodeDrag()
  stopBoundaryDrag()
  stopPortConnection()
  stopStagePan()
  stopMinimapNavigation()
  revokePreviewImageObjectUrls()
  window.removeEventListener('keydown', handleKeydown)
  window.removeEventListener('resize', updateStageSize)
  resizeObserver?.disconnect()
})
</script>
