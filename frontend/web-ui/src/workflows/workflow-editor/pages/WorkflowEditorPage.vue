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

      <WorkflowInspectorShell
        :collapsed="inspectorCollapsed"
        :show-new-app-draft-panel="showNewAppDraftPanel"
        :new-workflow-app-draft="newWorkflowAppDraft"
        :new-workflow-app-save-blocker="newWorkflowAppSaveBlocker"
        :show-app-contract-panel="showAppContractPanel"
        :app-input-bindings="appInputBindings"
        :app-output-bindings="appOutputBindings"
        :inspector-detail="inspectorDetail"
        :read-graph-node-title="readGraphNodeTitle"
        :binding-endpoint-text="bindingEndpointText"
        :binding-display-name="bindingDisplayName"
        :binding-kind-select-options="bindingKindSelectOptions"
        :get-binding-payload-type-id="getBindingPayloadTypeId"
        :preview-input-bindings="previewInputBindings"
        :preview-input-state="previewInputState"
        :preview-blocking-messages="previewBlockingMessages"
        :preview-help-text="previewHelpText"
        :image-ref-transport-kind-options="imageRefTransportKindOptions"
        :preview-binding-help-text="previewBindingHelpText"
        :last-preview-run="lastPreviewRun"
        :last-preview-failure-message="lastPreviewFailureMessage"
        :last-preview-failure-node-label="lastPreviewFailureNodeLabel"
        :last-preview-failure-location="lastPreviewFailureLocation"
        :last-preview-failure-detail-message="lastPreviewFailureDetailMessage"
        :last-preview-failure-details="lastPreviewFailureDetails"
        :last-preview-failure-details-json="lastPreviewFailureDetailsJson"
        :last-preview-http-response="lastPreviewHttpResponse"
        :last-preview-http-response-body-value="lastPreviewHttpResponseBodyValue"
        :last-preview-http-status="lastPreviewHttpStatus"
        :last-preview-http-response-json="lastPreviewHttpResponseJson"
        :last-preview-http-response-body-json="lastPreviewHttpResponseBodyJson"
        :has-preview-node-displays="hasPreviewNodeDisplays"
        @collapse="collapseInspector"
        @expand="expandInspector"
        @update-new-app-display-name="updateNewWorkflowDraftField('displayName', $event)"
        @update-new-app-application-id="updateNewWorkflowDraftField('applicationId', $event)"
        @update-new-app-graph-id="updateNewWorkflowDraftField('graphId', $event)"
        @update-new-app-graph-version="updateNewWorkflowDraftField('graphVersion', $event)"
        @update-new-app-description="updateNewWorkflowDraftField('description', $event)"
        @normalize-new-app-application-id="normalizeNewWorkflowApplicationId"
        @normalize-new-app-graph-id="normalizeNewWorkflowGraphId"
        @normalize-new-app-graph-version="normalizeNewWorkflowGraphVersion"
        @add-request-image-ref="addRequestImageRefInput"
        @add-request-image-base64="addRequestImageBase64Input"
        @update-node-enabled="updateNodeEnabled"
        @delete-selected-edge="deleteSelectedEdge"
        @update-binding-id="updateBindingIdFromEvent"
        @update-binding-display-name="updateBindingDisplayNameFromEvent"
        @update-binding-kind="updateBindingKindFromValue"
        @update-binding-required="updateBindingRequiredFromEvent"
        @delete-application-binding="deleteApplicationBinding"
        @add-preview-value-field="addPreviewValueField"
        @remove-preview-value-field="removePreviewValueField"
        @set-preview-image-ref-transport-kind="setPreviewImageRefTransportKind"
        @open-preview-json="openPreviewJsonViewer"
      />

      <WorkflowGraphOverlayLayer
        :minimap-visible="minimapVisible"
        :minimap-nodes="minimapNodes"
        :minimap-viewport-style="minimapViewportStyle"
        :is-minimap-node-selected="isMinimapNodeSelected"
        :context-menu="contextMenu"
        :context-menu-style="contextMenuStyle"
        :graph-theme="graphTheme"
        :save-disabled="saveDisabled"
        :preview-disabled="previewDisabled"
        :node-picker="nodePicker"
        :node-picker-definitions="nodePickerDefinitions"
        :node-picker-title="nodePickerTitle"
        :node-picker-required-port-direction="nodePickerRequiredPortDirection"
        :node-picker-required-payload-type-id="nodePickerRequiredPayloadTypeId"
        :loading="loading"
        :node-count="graphNodes.length"
        :is-new-app="isNewApp"
        @start-minimap-navigation="startMinimapNavigation"
        @toggle-minimap="toggleMinimap"
        @open-node-picker="openNodePickerFromContextMenu"
        @expose-app-input="exposeContextPortAsAppInput"
        @expose-app-output="exposeContextPortAsAppOutput"
        @delete-binding="deleteContextApplicationBinding"
        @delete-node="deleteSelectedNode"
        @delete-edge="deleteSelectedEdge"
        @reset-boundary-position="resetContextBoundaryPosition"
        @fit-view="fitView"
        @reset-view="resetView"
        @toggle-theme="toggleGraphTheme"
        @save="saveCurrentWorkflowApp"
        @preview="runPreview"
        @select-node-from-picker="selectNodeFromPicker"
        @close-node-picker="closeNodePicker"
      />
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
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'

import { usePreferencesStore } from '@/app/stores/preferences.store'
import { useProjectStore } from '@/app/stores/project.store'
import type { SupportedLocale } from '@/platform/i18n'
import InlineError from '@/shared/ui/feedback/InlineError.vue'
import WorkflowBoundaryNodeLayer from '../components/WorkflowBoundaryNodeLayer.vue'
import WorkflowGraphLinksLayer from '../components/WorkflowGraphLinksLayer.vue'
import WorkflowGraphNodeLayer from '../components/WorkflowGraphNodeLayer.vue'
import WorkflowGraphOverlayLayer from '../components/WorkflowGraphOverlayLayer.vue'
import WorkflowGraphToolbar from '../components/WorkflowGraphToolbar.vue'
import WorkflowInspectorShell from '../components/WorkflowInspectorShell.vue'
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
      enabled: true,
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

function updateNodeEnabled(node: GraphNodeView, event: Event): void {
  const target = event.target
  node.node.enabled = target instanceof HTMLInputElement ? target.checked : node.node.enabled !== false
}

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
