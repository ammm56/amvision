<template>
  <section class="workflow-graph-workbench" :class="`workflow-graph-workbench--${graphTheme}`">
    <WorkflowGraphToolbar
      :editor-title="editorTitle"
      :node-count="graphNodes.length"
      :edge-count="graphLinks.length"
      :runtime-state="workflowApp?.primaryRuntime?.observed_state ?? null"
      :preview-run-label="lastPreviewRun ? formatPreviewRunStatusLabel(lastPreviewRun.state) : null"
      :preview-run-tone="lastPreviewRun ? readPreviewRunBadgeTone(lastPreviewRun.state) : 'neutral'"
      :status-message="toolbarStatusMessage"
      :loading="loading"
      :graph-theme="graphTheme"
      :preview-disabled="previewDisabled"
      :save-disabled="saveDisabled"
      @refresh="loadPage"
      @toggle-theme="toggleGraphTheme"
      @preview="runPreview"
      @save="saveCurrentWorkflowApp"
    />

    <div
      ref="canvasRef"
      class="workflow-graph-stage"
      @mousedown="startStagePan"
      @wheel="handleStageWheel"
      @contextmenu.prevent="openStageContextMenu"
    >
      <InlineError v-if="errorMessage" class="workflow-graph-error" :message="errorMessage" />

      <div class="workflow-graph-world" :style="worldTransformStyle">
        <WorkflowGraphLinksLayer
          :links="graphLinks"
          :midpoints="graphLinkMidpoints"
          :reconnect-handles="selectedEdgeReconnectHandles"
          :show-draft="Boolean(connectionDraft)"
          :draft-path="draftLinkPath"
          :link-path="linkPath"
          :is-link-selected="isGraphLinkSelected"
          @select-link="selectGraphLink"
          @open-link-context-menu="openGraphLinkContextMenu"
          @start-edge-target-reconnect="startEdgeTargetReconnect"
        />

        <WorkflowBoundaryNodeLayer
          :boundaries="appBoundaryNodes"
          :selected-boundary-kind="selectedBoundaryKind"
          :dragged-boundary-kind="boundaryDragState?.boundaryKind ?? null"
          :read-boundary-height="boundaryNodeHeight"
          :is-boundary-port-connected="isBoundaryPortConnected"
          :get-binding-payload-type-id="getBindingPayloadTypeId"
          @start-boundary-drag="startBoundaryDrag"
          @select-boundary="selectApplicationBoundary"
          @open-boundary-context-menu="openBoundaryContextMenu"
          @start-boundary-port-connection="startBoundaryPortConnection"
          @select-boundary-binding="selectBoundaryBinding"
          @open-boundary-port-context-menu="openBoundaryPortContextMenu"
        />

        <WorkflowGraphNodeLayer
          :nodes="graphNodes"
          :selected-node-id="selectedNodeId"
          :last-preview-failure-node-id="lastPreviewFailureNodeId"
          :read-node-height="nodeVisualHeight"
          :read-title="readGraphNodeTitle"
          :read-port-rows="nodePortRows"
          :read-port-label="readNodePortLabel"
          :is-port-connected="isPortConnected"
          :is-selected-edge-endpoint="isSelectedEdgeEndpoint"
          :is-draft-anchor-port="isDraftAnchorPort"
          :read-parameter-fields="nodeParameterFieldsForNode"
          :read-parameter-label="readNodeParameterLabel"
          :read-parameter-enum-index="readNodeParameterEnumIndex"
          :read-parameter-enum-options="nodeParameterEnumOptions"
          :is-boolean-parameter="isBooleanParameter"
          :read-parameter-boolean-value="readNodeParameterBooleanValue"
          :is-number-parameter="isNumberParameter"
          :read-parameter-text-value="readNodeParameterTextValue"
          :is-string-parameter="isStringParameter"
          :is-json-parameter="isJsonParameter"
          :read-parameter-json-text-value="readNodeParameterJsonTextValue"
          :read-parameter-json-placeholder="nodeParameterJsonPlaceholder"
          :read-preview-display="getPreviewNodeDisplay"
          :read-preview-display-tooltip="readPreviewNodeDisplayTooltip"
          @start-node-drag="startNodeDrag"
          @node-click="handleNodeClick"
          @open-node-context-menu="openNodeContextMenu"
          @start-port-connection="startPortConnection"
          @select-port-endpoint="selectPortEndpoint"
          @open-port-context-menu="openPortContextMenu"
          @update-enum-parameter="updateNodeParameterFromEnumValue"
          @update-checkbox-parameter="updateNodeParameterFromCheckboxEvent"
          @update-number-parameter="updateNodeParameterFromNumberEvent"
          @update-text-parameter="updateNodeParameterFromTextEvent"
          @update-json-parameter-draft="updateNodeParameterJsonDraft"
          @commit-json-parameter-draft="commitNodeParameterJsonDraft"
          @open-preview-display="openPreviewDisplayViewer"
          @open-preview-image="openImageViewer"
        />
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

      <WorkflowCanvasEmptyState :loading="loading" :node-count="graphNodes.length" :is-new-app="isNewApp" />
    </div>
    <WorkflowPreviewViewers
      :image="activeImageViewer"
      :table="activePreviewTable"
      :json="activePreviewJson"
      @close-image="closeImageViewer"
      @close-table="closePreviewTableViewer"
      @close-json="closePreviewJsonViewer"
    />
  </section>
</template>

<script setup lang="ts">
import { computed, ref, shallowRef } from 'vue'
import { PanelRightClose, PanelRightOpen } from '@lucide/vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'

import { usePreferencesStore } from '@/app/stores/preferences.store'
import { useProjectStore } from '@/app/stores/project.store'
import type { SupportedLocale } from '@/platform/i18n'
import { formatSystemDateTime } from '@/shared/formatters/date-time'
import EmptyState from '@/shared/ui/feedback/EmptyState.vue'
import InlineError from '@/shared/ui/feedback/InlineError.vue'
import WorkflowBoundaryNodeLayer from '../components/WorkflowBoundaryNodeLayer.vue'
import WorkflowCanvasEmptyState from '../components/WorkflowCanvasEmptyState.vue'
import WorkflowGraphContextMenu from '../components/WorkflowGraphContextMenu.vue'
import WorkflowGraphLinksLayer from '../components/WorkflowGraphLinksLayer.vue'
import WorkflowGraphMinimap from '../components/WorkflowGraphMinimap.vue'
import WorkflowGraphNodeLayer from '../components/WorkflowGraphNodeLayer.vue'
import WorkflowGraphToolbar from '../components/WorkflowGraphToolbar.vue'
import WorkflowAppContractPanel from '../components/WorkflowAppContractPanel.vue'
import WorkflowApplicationSummaryPanel from '../components/WorkflowApplicationSummaryPanel.vue'
import WorkflowEdgeDetailPanel from '../components/WorkflowEdgeDetailPanel.vue'
import WorkflowNewAppDraftPanel from '../components/WorkflowNewAppDraftPanel.vue'
import WorkflowNodeDetailPanel from '../components/WorkflowNodeDetailPanel.vue'
import WorkflowNodePicker from '../components/WorkflowNodePicker.vue'
import WorkflowPublicBindingEditorPanel from '../components/WorkflowPublicBindingEditorPanel.vue'
import WorkflowPreviewInputPanel from '../components/WorkflowPreviewInputPanel.vue'
import WorkflowPreviewRunResultPanel from '../components/WorkflowPreviewRunResultPanel.vue'
import WorkflowPreviewViewers from '../components/WorkflowPreviewViewers.vue'
import { useWorkflowCanvasPan } from '../canvas/useWorkflowCanvasPan'
import { useWorkflowCanvasViewport } from '../canvas/useWorkflowCanvasViewport'
import { useWorkflowBoundaryDrag } from '../canvas/useWorkflowBoundaryDrag'
import { useWorkflowConnectionInteractions } from '../canvas/useWorkflowConnectionInteractions'
import { useWorkflowEdgeHandles } from '../canvas/useWorkflowEdgeHandles'
import { useWorkflowNodeDrag } from '../canvas/useWorkflowNodeDrag'
import { useWorkflowPortConnections } from '../canvas/useWorkflowPortConnections'
import { useWorkflowStageGuards } from '../canvas/useWorkflowStageGuards'
import type { WorkflowLiteGraphAdapter } from '../canvas/graph-engine/litegraph-adapter'
import { useWorkflowConnectionRules } from '../connections/useWorkflowConnectionRules'
import { useWorkflowContextMenu, type WorkflowContextMenuState } from '../context/useWorkflowContextMenu'
import { useWorkflowGraphGeometry, type WorkflowGraphLinkView } from '../geometry/useWorkflowGraphGeometry'
import { useWorkflowPreviewDisplays } from '../preview/useWorkflowPreviewDisplays'
import { useWorkflowPreviewInputHelpers } from '../preview/useWorkflowPreviewInputHelpers'
import { previewImageRefTransportKindOptions, useWorkflowPreviewInputs } from '../preview/useWorkflowPreviewInputs'
import { formatPreviewRunStatusLabel, readPreviewRunBadgeTone, useWorkflowPreviewValidation } from '../preview/useWorkflowPreviewValidation'
import { useWorkflowDocumentBuilder } from '../documents/useWorkflowDocumentBuilder'
import { useWorkflowDocumentLoader } from '../documents/useWorkflowDocumentLoader'
import { useWorkflowNewAppDraft } from '../documents/useWorkflowNewAppDraft'
import { useWorkflowGraphPanelState } from '../panels/useWorkflowGraphPanelState'
import { useWorkflowInspectorPanel } from '../panels/useWorkflowInspectorPanel'
import { useWorkflowInspectorViewModel } from '../panels/useWorkflowInspectorViewModel'
import { useWorkflowEditorKeyboard } from '../shell/useWorkflowEditorKeyboard'
import { useWorkflowEditorLifecycle } from '../shell/useWorkflowEditorLifecycle'
import { useWorkflowGraphTheme } from '../shell/useWorkflowGraphTheme'
import { useWorkflowToolbarStatus } from '../shell/useWorkflowToolbarStatus'
import { useWorkflowPublicBindings, type WorkflowBoundaryKind } from '../bindings/useWorkflowPublicBindings'
import { useWorkflowBindingEditorActions } from '../bindings/useWorkflowBindingEditorActions'
import { useWorkflowBoundaryNodes, type WorkflowBoundaryNodeView } from '../bindings/useWorkflowBoundaryNodes'
import { useWorkflowGraphDeletion } from '../graph/useWorkflowGraphDeletion'
import { useWorkflowRequestImageInputs } from '../graph/useWorkflowRequestImageInputs'
import { useWorkflowNodeDisplayHelpers } from '../nodes/useWorkflowNodeDisplayHelpers'
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
import type { WorkflowAppDocument } from '../services/workflow-app.service'
import type { FlowApplicationBinding, WorkflowGraphEdge, WorkflowGraphInput, WorkflowGraphNode, WorkflowGraphOutput, WorkflowNodeCatalogResponse } from '../types'

type AppBoundaryKind = WorkflowBoundaryKind
type SelectValue = WorkflowNodeParameterSelectValue
type GraphLinkView = WorkflowGraphLinkView
type GraphNodeView = WorkflowGraphNodeView

type ContextMenuState = WorkflowContextMenuState<AppBoundaryKind>

type AppBoundaryNodeView = WorkflowBoundaryNodeView

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
  shouldIgnoreStagePointer,
  shouldIgnoreStageWheelTarget,
} = useWorkflowStageGuards()
const {
  inspectorCollapsed,
  collapseInspector,
  expandInspector,
} = useWorkflowInspectorPanel()
const {
  readGraphNodeTitle,
  readNodePortLabel,
  readNodeParameterLabel,
  nodePortRows,
} = useWorkflowNodeDisplayHelpers({
  currentLocale,
})
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
  closeImageViewer,
  closePreviewTableViewer,
  closePreviewJsonViewer,
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
  selectBoundaryBinding,
  isMinimapNodeSelected,
} = useWorkflowGraphPanelState({
  selectedNodeId,
  selectedBoundaryKind,
  appEntryBoundaryId,
  appResultBoundaryId,
  selectApplicationBoundary,
  setStatusMessage: (message) => {
    statusMessage.value = message
  },
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
  buildCurrentTemplate,
  buildCurrentApplication,
} = useWorkflowDocumentBuilder<GraphNodeView>({
  workflowApp,
  graphNodes,
  graphEdges,
  templateInputs,
  templateOutputs,
  applicationBindingsDraft,
  liteGraphAdapter,
  applyNewWorkflowTemplateSettings,
  buildNewWorkflowApplicationPatch,
  writeBoundaryPositionsToMetadata,
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
const {
  previewBindingHelpText,
  buildPreviewInputBindings,
} = useWorkflowPreviewInputHelpers({
  previewInputBindings,
  previewBlockingMessages,
  getBindingPayloadTypeId,
  buildPreviewInputBindingsPayload,
  setErrorMessage: (message) => {
    errorMessage.value = message
  },
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
const { toolbarStatusMessage } = useWorkflowToolbarStatus({
  statusMessage,
  lastPreviewRun,
  formatPreviewRunStatusLabel,
})

function getBindingPayloadTypeId(binding: FlowApplicationBinding): string {
  return readPublicBindingPayloadTypeId(binding)
}

function clampNumber(value: number, minValue: number, maxValue: number): number {
  return Math.min(maxValue, Math.max(minValue, value))
}

function setPreviewImageRefTransportKind(bindingId: string, value: SelectValue): void {
  updatePreviewImageRefTransportKind(bindingId, value)
}

useWorkflowEditorLifecycle({
  canvasRef,
  loadPage,
  handleKeydown,
  updateStageSize,
  stopNodeDrag,
  stopBoundaryDrag,
  stopPortConnection,
  stopStagePan,
  stopMinimapNavigation,
  revokePreviewImageObjectUrls,
})
</script>
