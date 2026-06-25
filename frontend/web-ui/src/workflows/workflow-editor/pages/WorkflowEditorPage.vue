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
              @click="inspectorCollapsed = true"
            >
              <PanelRightClose :size="15" />
            </button>
          </div>
        </div>
        <div v-if="workflowApp && isNewApp" class="workflow-graph-new-app-panel">
          <div class="workflow-graph-panel__header workflow-graph-panel__header--compact">
            <div>
              <p>Draft</p>
              <h2>首次保存</h2>
            </div>
            <StatusBadge :tone="newWorkflowAppSaveBlocker ? 'warning' : 'success'">{{ newWorkflowAppSaveBlocker ? '待完成' : '可保存' }}</StatusBadge>
          </div>
          <label class="workflow-graph-preview-field">
            <span>应用名称</span>
            <input v-model="newWorkflowAppDraft.displayName" placeholder="检测应用" />
          </label>
          <label class="workflow-graph-preview-field">
            <span>应用 id</span>
            <input v-model="newWorkflowAppDraft.applicationId" placeholder="inspection-app" @change="normalizeNewWorkflowApplicationId" />
          </label>
          <label class="workflow-graph-preview-field">
            <span>图 id</span>
            <input v-model="newWorkflowAppDraft.graphId" placeholder="inspection-graph" @change="normalizeNewWorkflowGraphId" />
          </label>
          <label class="workflow-graph-preview-field">
            <span>图版本</span>
            <input v-model="newWorkflowAppDraft.graphVersion" placeholder="1.0.0" @change="normalizeNewWorkflowGraphVersion" />
          </label>
          <label class="workflow-graph-preview-field">
            <span>说明</span>
            <input v-model="newWorkflowAppDraft.description" placeholder="可选" />
          </label>
          <p class="workflow-graph-preview-hint" :class="{ 'workflow-graph-preview-hint--danger': newWorkflowAppSaveBlocker }">
            {{ newWorkflowAppSaveBlocker || '首次保存会创建应用和图。' }}
          </p>
        </div>
        <div v-if="workflowApp" class="workflow-graph-app-contract">
          <div class="workflow-graph-panel__header workflow-graph-panel__header--compact">
            <h2>应用输入</h2>
            <StatusBadge tone="info">{{ appInputBindings.length }} / {{ appOutputBindings.length }}</StatusBadge>
          </div>
          <section class="workflow-graph-contract-section">
            <div class="workflow-graph-contract-actions">
              <Button size="sm" variant="secondary" type="button" @click="addRequestImageRefInput">
                <Plus :size="14" />
                request_image_ref
              </Button>
              <Button size="sm" variant="secondary" type="button" @click="addRequestImageBase64Input">
                <Plus :size="14" />
                request_image_base64
              </Button>
            </div>
            <div v-for="binding in appInputBindings" :key="`contract-input-${binding.binding_id}`" class="workflow-graph-contract-binding">
              <div>
                <strong>{{ binding.binding_id }}</strong>
                <span>{{ getBindingPayloadTypeId(binding) || 'unknown' }}</span>
              </div>
              <small>{{ binding.required ? '必填' : '可选' }} / {{ binding.binding_kind }}</small>
            </div>
          </section>
          <section class="workflow-graph-contract-section">
            <h3>应用输出</h3>
            <div v-for="binding in appOutputBindings" :key="`contract-output-${binding.binding_id}`" class="workflow-graph-contract-binding">
              <div>
                <strong>{{ binding.binding_id }}</strong>
                <span>{{ getBindingPayloadTypeId(binding) || 'unknown' }}</span>
              </div>
              <small>{{ binding.binding_kind }}</small>
            </div>
          </section>
        </div>
        <WorkflowNodeDetailPanel
          v-if="selectedNode"
          :node="selectedNode"
          :read-title="readGraphNodeTitle"
        />
        <div v-else-if="selectedEdge" class="workflow-graph-inspector-body">
          <div class="workflow-graph-inspector-row">
            <span>Edge</span>
            <strong>{{ selectedEdge.edge_id }}</strong>
          </div>
          <div class="workflow-graph-inspector-row">
            <span>Source</span>
            <strong>{{ selectedEdge.source_node_id }} / {{ selectedEdge.source_port }}</strong>
          </div>
          <div class="workflow-graph-inspector-row">
            <span>Target</span>
            <strong>{{ selectedEdge.target_node_id }} / {{ selectedEdge.target_port }}</strong>
          </div>
          <Button variant="danger" @click="deleteSelectedEdge">
            <Trash2 :size="16" />
            删除连线
          </Button>
        </div>
        <WorkflowPublicBindingEditorPanel
          v-else-if="selectedBoundaryKind"
          :title="selectedBoundaryTitle"
          :bindings="selectedBoundaryBindings"
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
        <div v-else-if="workflowApp" class="workflow-graph-inspector-body">
          <div class="workflow-graph-inspector-row">
            <span>应用</span>
            <strong>{{ workflowApp.applicationDocument.application_id }}</strong>
          </div>
          <div class="workflow-graph-inspector-row">
            <span>应用输入</span>
            <strong>{{ workflowApp.graphDocument.template_input_ids.join(', ') || t('common.noValue') }}</strong>
          </div>
          <div class="workflow-graph-inspector-row">
            <span>应用输出</span>
            <strong>{{ workflowApp.graphDocument.template_output_ids.join(', ') || t('common.noValue') }}</strong>
          </div>
          <div v-if="lastPreviewRun" class="workflow-graph-inspector-row">
            <span>Preview run</span>
            <strong>{{ lastPreviewRun.preview_run_id }} / {{ lastPreviewRun.state }}</strong>
          </div>
        </div>
        <EmptyState v-else :title="t('workflowEditor.editor.emptyInspectorTitle')" :description="t('workflowEditor.editor.emptyInspectorDescription')" />

        <WorkflowPreviewInputPanel
          v-if="workflowApp"
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
        @click.stop="inspectorCollapsed = false"
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
import { computed, nextTick, onMounted, onUnmounted, ref, shallowRef } from 'vue'
import { ArrowLeft, Moon, PanelRightClose, PanelRightOpen, Play, Plus, RefreshCw, Save, Sun, Trash2, Workflow } from '@lucide/vue'
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
import { useWorkflowBoundaryDrag } from '../canvas/useWorkflowBoundaryDrag'
import { useWorkflowPortConnections, type WorkflowConnectionDraftState, type WorkflowPortDirection, type WorkflowPortReference } from '../canvas/useWorkflowPortConnections'
import { createWorkflowLiteGraphAdapter, type WorkflowLiteGraphAdapter } from '../canvas/graph-engine/litegraph-adapter'
import { type WorkflowCanvasGraphSnapshot } from '../canvas/graph-engine/workflow-graph-conversion'
import { useWorkflowConnectionRules } from '../connections/useWorkflowConnectionRules'
import { useWorkflowGraphGeometry, type WorkflowGraphLinkView } from '../geometry/useWorkflowGraphGeometry'
import { useWorkflowPreviewDisplays } from '../preview/useWorkflowPreviewDisplays'
import { previewImageRefTransportKindOptions, useWorkflowPreviewInputs } from '../preview/useWorkflowPreviewInputs'
import { formatPreviewRunStatusLabel, readPreviewRunBadgeTone, useWorkflowPreviewValidation } from '../preview/useWorkflowPreviewValidation'
import { buildPublicPortMetadata, createUniquePublicId, normalizePublicIdentifier, useWorkflowPublicBindings, type WorkflowBoundaryKind } from '../bindings/useWorkflowPublicBindings'
import { useWorkflowBoundaryNodes, type WorkflowBoundaryNodeView } from '../bindings/useWorkflowBoundaryNodes'
import { useWorkflowGraphDeletion } from '../graph/useWorkflowGraphDeletion'
import { useWorkflowRequestImageInputs } from '../graph/useWorkflowRequestImageInputs'
import {
  applyMissingNodeParameterDefaults,
  buildInitialNodeParameters,
  useWorkflowNodeParameters,
  type WorkflowNodeParameterSelectValue,
} from '../parameters/useWorkflowNodeParameters'
import { useWorkflowPreflight } from '../validation/useWorkflowPreflight'
import { useWorkflowEditorActions } from '../actions/useWorkflowEditorActions'
import { useWorkflowSaveRunFeedback } from '../actions/useWorkflowSaveRunFeedback'
import { useWorkflowSaveRunOrchestration } from '../actions/useWorkflowSaveRunOrchestration'
import { resolveNodeDefinitionDisplayName, resolveNodeParameterDisplayName, resolveNodePortDisplayName } from '../node-definition-localization'
import { getWorkflowNodeCatalog } from '../services/node-catalog.service'
import { getWorkflowApp, type WorkflowAppDocument } from '../services/workflow-app.service'
import type { FlowApplication, FlowApplicationBinding, NodeDefinition, NodeParameterUiField, NodePortDefinition, WorkflowApplicationDocument, WorkflowGraphEdge, WorkflowGraphInput, WorkflowGraphNode, WorkflowGraphOutput, WorkflowGraphTemplate, WorkflowNodeCatalogResponse, WorkflowTemplateDocument } from '../types'

interface GraphNodeView {
  node: WorkflowGraphNode
  definition: NodeDefinition | null
  title: string
  x: number
  y: number
  width: number
  inputs: NodePortDefinition[]
  outputs: NodePortDefinition[]
}

interface DragState {
  nodeId: string
  offsetX: number
  offsetY: number
}

type AppBoundaryKind = WorkflowBoundaryKind
type SelectValue = WorkflowNodeParameterSelectValue
type GraphLinkView = WorkflowGraphLinkView

type PortDirection = WorkflowPortDirection

type PortReference = WorkflowPortReference

type ConnectionDraftState = WorkflowConnectionDraftState

interface ContextMenuState {
  x: number
  y: number
  worldX: number
  worldY: number
  nodeId: string | null
  edgeId: string | null
  port: PortReference | null
  boundaryKind?: AppBoundaryKind | null
  bindingId?: string | null
}

interface NodePickerState {
  x: number
  y: number
  worldX: number
  worldY: number
  mode: 'context-menu' | 'link-drop'
  connectionDraft: ConnectionDraftState | null
}

interface NewWorkflowAppDraftState {
  applicationId: string
  displayName: string
  graphId: string
  graphVersion: string
  description: string
}

type RequiredNodePickerPortDirection = 'input' | 'output'

interface MinimapNodeView {
  nodeId: string
  style: Record<string, string>
}

type AppBoundaryNodeView = WorkflowBoundaryNodeView

interface NodePortRowView {
  key: string
  input: NodePortDefinition | null
  output: NodePortDefinition | null
}

interface EdgeHandleView {
  key: string
  edgeId: string
  x: number
  y: number
  link: GraphLinkView
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
const newWorkflowAppDraft = ref<NewWorkflowAppDraftState>(createNewWorkflowAppDraftState())
const selectedNodeId = ref<string | null>(null)
const selectedEdgeId = ref<string | null>(null)
const selectedBoundaryKind = ref<AppBoundaryKind | null>(null)
const dragState = ref<DragState | null>(null)
const suppressNextNodeClick = ref(false)
const minimapVisible = ref(true)
const inspectorCollapsed = ref(false)
const contextMenu = ref<ContextMenuState | null>(null)
const nodePicker = ref<NodePickerState | null>(null)
const complexParameterDrafts = ref<Record<string, string>>({})
const viewportX = ref(0)
const viewportY = ref(0)
const viewportScale = ref(1)
const stageSize = ref({ width: 1, height: 1 })
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
const canvasRef = ref<HTMLElement | null>(null)
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
  setSelection: (selection) => {
    selectedNodeId.value = selection.nodeId
    selectedEdgeId.value = selection.edgeId
    selectedBoundaryKind.value = selection.boundaryKind
  },
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
  setSelection: (selection) => {
    selectedNodeId.value = selection.nodeId
    selectedEdgeId.value = selection.edgeId
    selectedBoundaryKind.value = selection.boundaryKind
  },
  clearTransientUi,
  setStatusMessage: (message) => {
    statusMessage.value = message
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
  boundaryDragState,
  startBoundaryDrag,
  stopBoundaryDrag,
} = useWorkflowBoundaryDrag<AppBoundaryKind>({
  screenToWorld,
  canStart: () => !connectionDraft.value,
  onStart: (boundaryKind) => {
    selectedBoundaryKind.value = boundaryKind
    selectedNodeId.value = null
    selectedEdgeId.value = null
    contextMenu.value = null
    nodePicker.value = null
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

const minimapWidth = 184
const minimapHeight = 116
const minimapPadding = 10
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
const minViewportScale = 0.35
const maxViewportScale = 2.4

const selectedProjectId = computed(() => projectStore.selectedProjectId)
const routeApplicationId = computed(() => (typeof route.params.applicationId === 'string' ? route.params.applicationId : ''))
const isNewApp = computed(() => route.path.endsWith('/new'))
const graphTheme = computed(() => preferencesStore.theme)
const nodeDefinitionsById = computed(() => new Map((nodeCatalog.value?.node_definitions ?? []).map((definition) => [definition.node_type_id, definition])))
const nodePickerDefinitions = computed(() => nodeCatalog.value?.node_definitions ?? [])
const {
  runWorkflowPreflight,
  applyWorkflowValidationIssue,
} = useWorkflowPreflight({
  graphNodes,
  graphEdges,
  nodeDefinitionsById,
  portsCanConnect,
  focusGraphNode,
  setSelection: (selection) => {
    selectedNodeId.value = selection.nodeId
    selectedEdgeId.value = selection.edgeId
    selectedBoundaryKind.value = selection.boundaryKind
  },
  clearTransientUi,
  setErrorMessage: (message) => {
    errorMessage.value = message
  },
  setStatusMessage: (message) => {
    statusMessage.value = message
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
  clearContextMenu: () => {
    contextMenu.value = null
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
const nodePickerTitle = computed(() => nodePicker.value?.mode === 'link-drop' ? t('workflowEditor.nodePicker.selectAndConnect') : t('workflowEditor.nodePicker.addNode'))
const nodePickerRequiredPortDirection = computed<RequiredNodePickerPortDirection | null>(() => {
  const draft = nodePicker.value?.connectionDraft
  if (!draft) return null
  return draft.anchorDirection === 'output' ? 'input' : 'output'
})
const nodePickerRequiredPayloadTypeId = computed(() => {
  const draft = nodePicker.value?.connectionDraft
  if (!draft) return null
  return getConnectionDraftPayloadTypeId(draft)
})
const editorTitle = computed(() => isNewApp.value ? newWorkflowAppDraft.value.displayName || t('workflowEditor.editor.newTitle') : workflowApp.value?.applicationDocument.application.display_name || routeApplicationId.value)
const newWorkflowAppSaveBlocker = computed(() => readNewWorkflowAppSaveBlocker())
const saveDisabled = computed(() => saving.value || !workflowApp.value || Boolean(newWorkflowAppSaveBlocker.value))
const previewDisabled = computed(() => previewing.value || !workflowApp.value || isNewApp.value || Boolean(newWorkflowAppSaveBlocker.value))
const selectedNode = computed(() => graphNodes.value.find((node) => node.node.node_id === selectedNodeId.value) ?? null)
const selectedEdge = computed(() => graphEdges.value.find((edge) => edge.edge_id === selectedEdgeId.value) ?? null)
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
const graphLinkMidpoints = computed<EdgeHandleView[]>(() => graphLinks.value.map((link) => ({
  key: `${link.edgeId}-midpoint`,
  edgeId: link.edgeId,
  link,
  ...linkPointAt(link, 0.5),
})))
const selectedEdgeReconnectHandles = computed<EdgeHandleView[]>(() => {
  const link = graphLinks.value.find((item) => item.edgeId === selectedEdgeId.value && item.linkKind === 'edge')
  if (!link) return []
  return [{ key: `${link.edgeId}-reconnect`, edgeId: link.edgeId, link, ...linkPointAt(link, 0.5) }]
})
const worldTransformStyle = computed(() => ({
  transform: `translate(${viewportX.value}px, ${viewportY.value}px) scale(${viewportScale.value})`,
}))
const contextMenuStyle = computed<Record<string, string>>(() => {
  if (!contextMenu.value) return {} as Record<string, string>
  return { left: `${contextMenu.value.x}px`, top: `${contextMenu.value.y}px` }
})
const worldBounds = computed(() => calculateWorldBounds())
const minimapScale = computed(() => {
  const bounds = worldBounds.value
  const availableWidth = minimapWidth - minimapPadding * 2
  const availableHeight = minimapHeight - minimapPadding * 2
  return Math.min(availableWidth / Math.max(bounds.width, 1), availableHeight / Math.max(bounds.height, 1))
})
const minimapNodes = computed<MinimapNodeView[]>(() => {
  const bounds = worldBounds.value
  const scale = minimapScale.value
  const regularNodes = graphNodes.value.map((node) => ({
    nodeId: node.node.node_id,
    style: {
      left: `${minimapPadding + (node.x - bounds.minX) * scale}px`,
      top: `${minimapPadding + (node.y - bounds.minY) * scale}px`,
      width: `${Math.max(node.width * scale, 8)}px`,
      height: `${Math.max(72 * scale, 5)}px`,
    },
  }))
  const boundaryNodes = appBoundaryNodes.value.map((boundary) => ({
    nodeId: boundary.id,
    style: {
      left: `${minimapPadding + (boundary.x - bounds.minX) * scale}px`,
      top: `${minimapPadding + (boundary.y - bounds.minY) * scale}px`,
      width: `${Math.max(boundary.width * scale, 8)}px`,
      height: `${Math.max(boundaryNodeHeight(boundary) * scale, 5)}px`,
    },
  }))
  return [...regularNodes, ...boundaryNodes]
})
const minimapViewportStyle = computed(() => {
  const bounds = worldBounds.value
  const scale = minimapScale.value
  const viewLeft = -viewportX.value / viewportScale.value
  const viewTop = -viewportY.value / viewportScale.value
  return {
    left: `${minimapPadding + (viewLeft - bounds.minX) * scale}px`,
    top: `${minimapPadding + (viewTop - bounds.minY) * scale}px`,
    width: `${Math.max((stageSize.value.width / viewportScale.value) * scale, 8)}px`,
    height: `${Math.max((stageSize.value.height / viewportScale.value) * scale, 8)}px`,
  }
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

function createNewWorkflowAppDraftState(): NewWorkflowAppDraftState {
  const suffix = new Date().toISOString().replace(/[-:T.Z]/g, '').slice(0, 14)
  return {
    applicationId: `workflow-app-${suffix}`,
    displayName: '新建应用',
    graphId: `workflow-graph-${suffix}`,
    graphVersion: '1.0.0',
    description: '',
  }
}

function normalizeNewWorkflowApplicationId(event?: Event): void {
  const normalizedApplicationId = normalizeWorkflowIdentifier(newWorkflowAppDraft.value.applicationId, 'workflow-app')
  newWorkflowAppDraft.value.applicationId = normalizedApplicationId
  if (event?.target instanceof HTMLInputElement) event.target.value = normalizedApplicationId
}

function normalizeNewWorkflowGraphId(event?: Event): void {
  const normalizedGraphId = normalizeWorkflowIdentifier(newWorkflowAppDraft.value.graphId, `${newWorkflowAppDraft.value.applicationId || 'workflow'}-graph`)
  newWorkflowAppDraft.value.graphId = normalizedGraphId
  if (event?.target instanceof HTMLInputElement) event.target.value = normalizedGraphId
}

function normalizeNewWorkflowGraphVersion(event?: Event): void {
  const normalizedGraphVersion = newWorkflowAppDraft.value.graphVersion.trim() || '1.0.0'
  newWorkflowAppDraft.value.graphVersion = normalizedGraphVersion
  if (event?.target instanceof HTMLInputElement) event.target.value = normalizedGraphVersion
}

function readNewWorkflowAppSaveBlocker(): string | null {
  if (!isNewApp.value) return null
  const draft = newWorkflowAppDraft.value
  if (!draft.displayName.trim()) return '填写应用名称后才能保存。'
  if (!draft.applicationId.trim()) return '填写应用 id 后才能保存。'
  if (!draft.graphId.trim()) return '填写图 id 后才能保存。'
  if (!draft.graphVersion.trim()) return '填写图版本后才能保存。'
  if (graphNodes.value.length === 0) return '至少添加一个节点后才能首次保存。'
  return null
}

function createLocalWorkflowAppDraft(): WorkflowAppDocument {
  const template = createLocalWorkflowTemplate()
  const application = createLocalFlowApplication(template)
  const now = new Date().toISOString()
  return {
    applicationDocument: createLocalWorkflowApplicationDocument(application, template, now),
    graphDocument: createLocalWorkflowTemplateDocument(template, now),
    runtimes: [],
    primaryRuntime: null,
  }
}

function createLocalWorkflowTemplate(): WorkflowGraphTemplate {
  const draft = newWorkflowAppDraft.value
  return {
    format_id: 'amvision.workflow-graph-template.v1',
    template_id: draft.graphId,
    template_version: draft.graphVersion,
    display_name: `${draft.displayName || draft.graphId} 图`,
    description: draft.description.trim(),
    nodes: [],
    edges: [],
    template_inputs: [],
    template_outputs: [],
    metadata: { source: 'workflow-graph-editor' },
  }
}

function createLocalFlowApplication(template: WorkflowGraphTemplate): FlowApplication {
  const draft = newWorkflowAppDraft.value
  return {
    format_id: 'amvision.flow-application.v1',
    application_id: draft.applicationId,
    display_name: draft.displayName,
    template_ref: {
      template_id: template.template_id,
      template_version: template.template_version,
      source_kind: 'json-file',
      source_uri: buildWorkflowTemplateSourceUri(selectedProjectId.value, template.template_id, template.template_version),
      metadata: {},
    },
    runtime_mode: 'python-json-workflow',
    description: draft.description.trim(),
    bindings: [],
    metadata: { source: 'workflow-graph-editor' },
  }
}

function buildWorkflowTemplateSourceUri(projectId: string, templateId: string, templateVersion: string): string {
  return `workflows/projects/${projectId}/templates/${templateId}/versions/${templateVersion}/template.json`
}

function normalizeWorkflowIdentifier(value: string, fallback: string): string {
  const normalized = value.trim().replace(/[\\/]+/g, '_').replace(/\.{2,}/g, '_').replace(/[^a-zA-Z0-9._-]+/g, '_').replace(/^[_ .-]+|[_ .-]+$/g, '')
  return normalized || fallback
}

function createLocalWorkflowTemplateDocument(template: WorkflowGraphTemplate, now: string): WorkflowTemplateDocument {
  return {
    valid: false,
    template_id: template.template_id,
    template_version: template.template_version,
    node_count: template.nodes.length,
    edge_count: template.edges.length,
    template_input_ids: template.template_inputs.map((input) => input.input_id),
    template_output_ids: template.template_outputs.map((output) => output.output_id),
    referenced_node_type_ids: template.nodes.map((node) => node.node_type_id),
    project_id: selectedProjectId.value,
    object_key: '',
    created_at: now,
    updated_at: now,
    created_by: null,
    updated_by: null,
    template,
  }
}

function createLocalWorkflowApplicationDocument(application: FlowApplication, template: WorkflowGraphTemplate, now: string): WorkflowApplicationDocument {
  const inputBindingIds = application.bindings.filter((binding) => binding.direction === 'input').map((binding) => binding.binding_id)
  const outputBindingIds = application.bindings.filter((binding) => binding.direction === 'output').map((binding) => binding.binding_id)
  return {
    valid: false,
    application_id: application.application_id,
    template_id: template.template_id,
    template_version: template.template_version,
    binding_count: application.bindings.length,
    input_binding_ids: inputBindingIds,
    output_binding_ids: outputBindingIds,
    project_id: selectedProjectId.value,
    object_key: '',
    created_at: now,
    updated_at: now,
    created_by: null,
    updated_by: null,
    template_summary: null,
    application,
  }
}

function applyNewWorkflowTemplateSettings(template: WorkflowGraphTemplate): WorkflowGraphTemplate {
  if (!isNewApp.value) return template
  const draft = newWorkflowAppDraft.value
  return {
    ...template,
    template_id: draft.graphId.trim(),
    template_version: draft.graphVersion.trim(),
    display_name: `${draft.displayName.trim() || draft.graphId.trim()} 图`,
    description: draft.description.trim(),
    metadata: { ...template.metadata, source: template.metadata.source ?? 'workflow-graph-editor' },
  }
}

function selectBoundaryBinding(kind: 'entry' | 'result', binding: FlowApplicationBinding): void {
  selectedBoundaryKind.value = kind
  selectedNodeId.value = null
  selectedEdgeId.value = null
  connectionDraft.value = null
  contextMenu.value = null
  nodePicker.value = null
  statusMessage.value = `已选择 ${binding.binding_id}`
}

function getBindingPayloadTypeId(binding: FlowApplicationBinding): string {
  return readPublicBindingPayloadTypeId(binding)
}

function readNumber(value: unknown, fallback: number): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback
}

function readNodePosition(node: WorkflowGraphNode, index: number, fallbackByNodeId: Map<string, { x: number; y: number }>): { x: number; y: number } {
  const rawX = node.ui_state.x ?? node.ui_state.pos_x ?? node.ui_state.position_x
  const rawY = node.ui_state.y ?? node.ui_state.pos_y ?? node.ui_state.position_y
  const fallback = fallbackByNodeId.get(node.node_id) ?? { x: 360 + (index % 3) * 280, y: 120 + Math.floor(index / 3) * 180 }
  return {
    x: readNumber(rawX, fallback.x),
    y: readNumber(rawY, fallback.y),
  }
}

function buildFallbackPositions(nodes: WorkflowGraphNode[], edges: WorkflowGraphEdge[]): Map<string, { x: number; y: number }> {
  const nodeIds = new Set(nodes.map((node) => node.node_id))
  const incomingCounts = new Map(nodes.map((node) => [node.node_id, 0]))
  const outgoingNodes = new Map(nodes.map((node) => [node.node_id, [] as string[]]))
  for (const edge of edges) {
    if (!nodeIds.has(edge.source_node_id) || !nodeIds.has(edge.target_node_id)) continue
    outgoingNodes.get(edge.source_node_id)?.push(edge.target_node_id)
    incomingCounts.set(edge.target_node_id, (incomingCounts.get(edge.target_node_id) ?? 0) + 1)
  }

  const queue = nodes.filter((node) => (incomingCounts.get(node.node_id) ?? 0) === 0).map((node) => node.node_id)
  const depthByNodeId = new Map(nodes.map((node) => [node.node_id, 0]))
  while (queue.length > 0) {
    const nodeId = queue.shift()
    if (!nodeId) continue
    const nextDepth = (depthByNodeId.get(nodeId) ?? 0) + 1
    for (const targetNodeId of outgoingNodes.get(nodeId) ?? []) {
      depthByNodeId.set(targetNodeId, Math.max(depthByNodeId.get(targetNodeId) ?? 0, nextDepth))
      incomingCounts.set(targetNodeId, (incomingCounts.get(targetNodeId) ?? 1) - 1)
      if ((incomingCounts.get(targetNodeId) ?? 0) === 0) {
        queue.push(targetNodeId)
      }
    }
  }

  const columns = new Map<number, WorkflowGraphNode[]>()
  for (const node of nodes) {
    const depth = depthByNodeId.get(node.node_id) ?? 0
    const columnNodes = columns.get(depth) ?? []
    columnNodes.push(node)
    columns.set(depth, columnNodes)
  }

  const positions = new Map<string, { x: number; y: number }>()
  for (const [depth, columnNodes] of columns) {
    columnNodes.forEach((node, rowIndex) => {
      positions.set(node.node_id, { x: 360 + depth * 320, y: 120 + rowIndex * 230 })
    })
  }
  return positions
}

function inferPortsFromEdges(node: WorkflowGraphNode, direction: 'input' | 'output'): NodePortDefinition[] {
  const edgeNames = new Set<string>()
  for (const edge of graphEdges.value) {
    if (direction === 'input' && edge.target_node_id === node.node_id) {
      edgeNames.add(edge.target_port)
    }
    if (direction === 'output' && edge.source_node_id === node.node_id) {
      edgeNames.add(edge.source_port)
    }
  }
  return [...edgeNames].map((name) => ({
    name,
    display_name: name,
    payload_type_id: '',
    description: '',
    required: true,
    multiple: false,
    metadata: {},
  }))
}

function buildGraphNodeView(node: WorkflowGraphNode, index: number, fallbackByNodeId: Map<string, { x: number; y: number }>): GraphNodeView {
  const definition = nodeDefinitionsById.value.get(node.node_type_id) ?? null
  const normalizedNode = definition ? applyMissingNodeParameterDefaults(node, definition) : node
  const position = readNodePosition(normalizedNode, index, fallbackByNodeId)
  const defaultWidth = definition ? buildDefaultGraphNodeWidth(definition) : 256
  return {
    node: normalizedNode,
    definition,
    title: definition?.display_name || normalizedNode.node_type_id,
    x: position.x,
    y: position.y,
    width: normalizeGraphNodeWidth(normalizedNode.ui_state.width, defaultWidth),
    inputs: definition?.input_ports.length ? definition.input_ports : inferPortsFromEdges(normalizedNode, 'input'),
    outputs: definition?.output_ports.length ? definition.output_ports : inferPortsFromEdges(normalizedNode, 'output'),
  }
}

function buildGraphNodeViews(nodes: WorkflowGraphNode[]): GraphNodeView[] {
  const fallbackByNodeId = buildFallbackPositions(nodes, graphEdges.value)
  return nodes.map((node, index) => buildGraphNodeView(node, index, fallbackByNodeId))
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

function selectValueToString(value: SelectValue): string {
  return typeof value === 'string' ? value : String(value ?? '')
}

function isSelectedEdgeEndpoint(nodeId: string, portName: string, direction: PortDirection): boolean {
  const edge = selectedEdge.value
  if (!edge) return false
  return direction === 'input'
    ? edge.target_node_id === nodeId && edge.target_port === portName
    : edge.source_node_id === nodeId && edge.source_port === portName
}

function isDraftAnchorPort(nodeId: string, portName: string, direction: PortDirection): boolean {
  const draft = connectionDraft.value
  return Boolean(draft && draft.anchorNodeId === nodeId && draft.anchorPort === portName && draft.anchorDirection === direction)
}

function selectNode(nodeId: string): void {
  selectedNodeId.value = nodeId
  selectedEdgeId.value = null
  selectedBoundaryKind.value = null
  connectionDraft.value = null
  contextMenu.value = null
  nodePicker.value = null
}

function handleNodeClick(nodeId: string): void {
  if (suppressNextNodeClick.value) {
    suppressNextNodeClick.value = false
    return
  }
  selectNode(nodeId)
}

function suppressNodeClickOnce(): void {
  suppressNextNodeClick.value = true
  window.setTimeout(() => {
    suppressNextNodeClick.value = false
  }, 0)
}

function selectEdge(edgeId: string): void {
  selectedEdgeId.value = edgeId
  selectedNodeId.value = null
  selectedBoundaryKind.value = null
  connectionDraft.value = null
  contextMenu.value = null
  nodePicker.value = null
}

function selectGraphLink(link: GraphLinkView): void {
  if (link.linkKind === 'edge') {
    selectEdge(link.edgeId)
    return
  }
  selectApplicationBoundary(link.linkKind === 'template-input' ? 'entry' : 'result')
}

function isGraphLinkSelected(link: GraphLinkView): boolean {
  if (link.linkKind === 'edge') return selectedEdgeId.value === link.edgeId
  if (link.linkKind === 'template-input') return selectedBoundaryKind.value === 'entry'
  return selectedBoundaryKind.value === 'result'
}

function openGraphLinkContextMenu(event: MouseEvent, link: GraphLinkView): void {
  if (link.linkKind === 'edge') {
    openEdgeContextMenu(event, link)
    return
  }
  const boundaryKind: AppBoundaryKind = link.linkKind === 'template-input' ? 'entry' : 'result'
  selectedBoundaryKind.value = boundaryKind
  selectedNodeId.value = null
  selectedEdgeId.value = null
  const position = screenToWorld(event.clientX, event.clientY)
  nodePicker.value = null
  contextMenu.value = { x: event.clientX, y: event.clientY, worldX: position.x, worldY: position.y, nodeId: null, edgeId: null, port: null, boundaryKind, bindingId: link.bindingId ?? null }
}

function selectPortEndpoint(node: GraphNodeView, port: NodePortDefinition, direction: PortDirection): void {
  const edge = direction === 'input'
    ? findInputEdge(node.node.node_id, port.name)
    : findOutputEdge(node.node.node_id, port.name)
  if (edge) {
    selectEdge(edge.edge_id)
    return
  }
  selectNode(node.node.node_id)
}

function selectApplicationBoundary(kind: AppBoundaryKind): void {
  selectedBoundaryKind.value = kind
  selectedNodeId.value = null
  selectedEdgeId.value = null
  connectionDraft.value = null
  contextMenu.value = null
  nodePicker.value = null
}

function clearTransientUi(): void {
  connectionDraft.value = null
  contextMenu.value = null
  nodePicker.value = null
}

function isMinimapNodeSelected(nodeId: string): boolean {
  if (selectedNodeId.value === nodeId) return true
  if (selectedBoundaryKind.value === 'entry') return nodeId === appEntryBoundaryId
  if (selectedBoundaryKind.value === 'result') return nodeId === appResultBoundaryId
  return false
}

function addGraphNode(definition: NodeDefinition, rawX: number, rawY: number): GraphNodeView {
  const nodeId = createGraphNodeId(definition.node_type_id)
  const x = Math.round(rawX - 115)
  const y = Math.round(rawY - 40)
  const node: WorkflowGraphNode = {
    node_id: nodeId,
    node_type_id: definition.node_type_id,
    parameters: buildInitialNodeParameters(definition),
    ui_state: { x, y, width: buildDefaultGraphNodeWidth(definition) },
    metadata: {},
  }
  const graphNode = buildGraphNodeView(node, graphNodes.value.length, new Map([[nodeId, { x, y }]]))
  graphNodes.value.push(graphNode)
  selectedNodeId.value = nodeId
  selectedEdgeId.value = null
  selectedBoundaryKind.value = null
  statusMessage.value = '已添加节点'
  return graphNode
}

function buildDefaultGraphNodeWidth(definition: NodeDefinition): number {
  void definition
  return 256
}

function normalizeGraphNodeWidth(value: unknown, fallbackWidth: number): number {
  const width = readNumber(value, fallbackWidth)
  if ([250, 300, 320, 340].includes(width)) return fallbackWidth
  return width
}

function openNodePickerFromContextMenu(): void {
  const menu = contextMenu.value
  if (!menu) return
  const pickerWidth = 640
  const preferredX = menu.x + 198
  const hasRightSpace = typeof window === 'undefined' || preferredX + pickerWidth + 12 <= window.innerWidth
  nodePicker.value = {
    x: hasRightSpace ? preferredX : menu.x - pickerWidth - 8,
    y: menu.y,
    worldX: menu.worldX,
    worldY: menu.worldY,
    mode: 'context-menu',
    connectionDraft: null,
  }
}

function openNodePickerFromConnectionDraft(draft: ConnectionDraftState, event: MouseEvent): void {
  const position = screenToWorld(event.clientX, event.clientY)
  contextMenu.value = null
  nodePicker.value = {
    x: event.clientX + 8,
    y: event.clientY + 8,
    worldX: position.x,
    worldY: position.y,
    mode: 'link-drop',
    connectionDraft: { ...draft },
  }
  errorMessage.value = null
}

function closeNodePicker(): void {
  nodePicker.value = null
  contextMenu.value = null
}

function selectNodeFromPicker(definition: NodeDefinition): void {
  const picker = nodePicker.value
  if (!picker) return
  const graphNode = addGraphNode(definition, picker.worldX, picker.worldY)
  const connectionResult = picker.connectionDraft ? connectConnectionDraftToNewNode(picker.connectionDraft, graphNode) : true
  nodePicker.value = null
  contextMenu.value = null
  if (!connectionResult && picker.connectionDraft) {
    selectedNodeId.value = graphNode.node.node_id
  }
}

function createGraphNodeId(nodeTypeId: string): string {
  const baseId = nodeTypeId.replace(/[^a-zA-Z0-9]+/g, '_').replace(/^_+|_+$/g, '').toLowerCase() || 'node'
  const existingIds = new Set(graphNodes.value.map((node) => node.node.node_id))
  let candidateId = baseId
  let suffix = 1
  while (existingIds.has(candidateId)) {
    suffix += 1
    candidateId = `${baseId}_${suffix}`
  }
  return candidateId
}

function screenToWorld(clientX: number, clientY: number): { x: number; y: number } {
  const canvasBounds = canvasRef.value?.getBoundingClientRect()
  if (!canvasBounds) return { x: 0, y: 0 }
  return {
    x: (clientX - canvasBounds.left - viewportX.value) / viewportScale.value,
    y: (clientY - canvasBounds.top - viewportY.value) / viewportScale.value,
  }
}

function handleStageWheel(event: WheelEvent): void {
  if (shouldIgnoreStageWheelTarget(event.target)) return
  event.preventDefault()
  contextMenu.value = null
  nodePicker.value = null
  const wheelStep = Math.max(-3, Math.min(3, -event.deltaY / 100))
  const nextScale = clampNumber(viewportScale.value * Math.pow(1.12, wheelStep), minViewportScale, maxViewportScale)
  zoomViewportAt(event.clientX, event.clientY, nextScale)
}

function zoomViewportAt(clientX: number, clientY: number, nextScale: number): void {
  const canvasBounds = canvasRef.value?.getBoundingClientRect()
  if (!canvasBounds) return
  const stageX = clientX - canvasBounds.left
  const stageY = clientY - canvasBounds.top
  const worldX = (stageX - viewportX.value) / viewportScale.value
  const worldY = (stageY - viewportY.value) / viewportScale.value
  viewportScale.value = nextScale
  viewportX.value = stageX - worldX * nextScale
  viewportY.value = stageY - worldY * nextScale
}

function clampNumber(value: number, minValue: number, maxValue: number): number {
  return Math.min(maxValue, Math.max(minValue, value))
}

function startNodeDrag(event: MouseEvent, node: GraphNodeView): void {
  if (connectionDraft.value) return
  const worldPosition = screenToWorld(event.clientX, event.clientY)
  selectedNodeId.value = node.node.node_id
  selectedEdgeId.value = null
  selectedBoundaryKind.value = null
  contextMenu.value = null
  nodePicker.value = null
  dragState.value = {
    nodeId: node.node.node_id,
    offsetX: worldPosition.x - node.x,
    offsetY: worldPosition.y - node.y,
  }
  event.preventDefault()
  document.addEventListener('mousemove', moveDraggedNode)
  document.addEventListener('mouseup', stopNodeDrag)
}

function moveDraggedNode(event: MouseEvent): void {
  const drag = dragState.value
  if (!drag) return
  const targetNode = graphNodes.value.find((node) => node.node.node_id === drag.nodeId)
  if (!targetNode) return
  const worldPosition = screenToWorld(event.clientX, event.clientY)
  targetNode.x = Math.round(worldPosition.x - drag.offsetX)
  targetNode.y = Math.round(worldPosition.y - drag.offsetY)
  targetNode.node.ui_state = { ...targetNode.node.ui_state, x: targetNode.x, y: targetNode.y, width: targetNode.width }
}

function stopNodeDrag(): void {
  dragState.value = null
  document.removeEventListener('mousemove', moveDraggedNode)
  document.removeEventListener('mouseup', stopNodeDrag)
}

function startPortConnection(event: MouseEvent, node: GraphNodeView, port: NodePortDefinition, direction: PortDirection): void {
  if (event.button !== 0) return
  const existingInputEdge = direction === 'input' ? findInputEdge(node.node.node_id, port.name) : null
  if (existingInputEdge) {
    startEdgeTargetReconnect(event, existingInputEdge.edge_id)
    return
  }
  startConnectionDraft(event, node, port, direction)
}

function startBoundaryPortConnection(event: MouseEvent, boundary: AppBoundaryNodeView, binding: FlowApplicationBinding): void {
  if (event.button !== 0) return
  const started = startPortConnectionDraft(event, {
    anchorDirection: boundary.portDirection,
    anchorNodeId: boundary.id,
    anchorPort: binding.binding_id,
    anchorX: boundaryPortX(boundary),
    anchorY: boundaryPortY(boundary, binding.binding_id),
    replacingEdgeId: null,
  })
  if (!started) return
  selectedBoundaryKind.value = boundary.kind
  selectedNodeId.value = null
  selectedEdgeId.value = null
  contextMenu.value = null
  nodePicker.value = null
  errorMessage.value = null
}

function startConnectionDraft(event: MouseEvent, node: GraphNodeView, port: NodePortDefinition, anchorDirection: PortDirection, replacingEdgeId: string | null = null): void {
  const started = startPortConnectionDraft(event, {
    anchorDirection,
    anchorNodeId: node.node.node_id,
    anchorPort: port.name,
    anchorX: portX(node, anchorDirection),
    anchorY: portY(node, port.name, anchorDirection),
    replacingEdgeId,
  })
  if (!started) return
  selectedNodeId.value = node.node.node_id
  selectedEdgeId.value = null
  selectedBoundaryKind.value = null
  contextMenu.value = null
  nodePicker.value = null
  errorMessage.value = null
}

function startEdgeTargetReconnect(event: MouseEvent, edgeId: string): void {
  const link = graphLinks.value.find((item) => item.edgeId === edgeId && item.linkKind === 'edge')
  if (!link?.edge) return
  const edge = link.edge
  const sourceNode = graphNodes.value.find((node) => node.node.node_id === edge.source_node_id)
  const sourcePort = sourceNode?.outputs.find((port) => port.name === edge.source_port)
  if (!sourceNode || !sourcePort) return
  const started = startPortConnectionDraft(event, {
    anchorDirection: 'output',
    anchorNodeId: sourceNode.node.node_id,
    anchorPort: sourcePort.name,
    anchorX: link.sourceX,
    anchorY: link.sourceY,
    replacingEdgeId: edgeId,
  })
  if (!started) return
  selectedNodeId.value = null
  selectedEdgeId.value = edgeId
  selectedBoundaryKind.value = null
  contextMenu.value = null
  nodePicker.value = null
  errorMessage.value = null
}

function exposeContextPortAsAppInput(): void {
  const portRef = contextMenu.value?.port
  if (!portRef || portRef.direction !== 'input') return
  const node = graphNodes.value.find((item) => item.node.node_id === portRef.nodeId)
  const port = node?.inputs.find((item) => item.name === portRef.portName)
  if (!node || !port) return
  exposeNodeInputAsAppInput(node, port)
}

function exposeContextPortAsAppOutput(): void {
  const portRef = contextMenu.value?.port
  if (!portRef || portRef.direction !== 'output') return
  const node = graphNodes.value.find((item) => item.node.node_id === portRef.nodeId)
  const port = node?.outputs.find((item) => item.name === portRef.portName)
  if (!node || !port) return
  exposeNodeOutputAsAppOutput(node, port)
}

function exposeNodeInputAsAppInput(node: GraphNodeView, port: NodePortDefinition, options: { required?: boolean } = {}): void {
  if (!workflowApp.value) {
    errorMessage.value = '当前图还没有应用草稿，暂不能创建公开输入'
    return
  }
  const existingInput = templateInputs.value.find((input) => input.target_node_id === node.node.node_id && input.target_port === port.name)
  if (existingInput) {
    selectApplicationBoundary('entry')
    statusMessage.value = `${existingInput.input_id} 已经是应用输入`
    return
  }
  if (findInputEdge(node.node.node_id, port.name) && !port.multiple) {
    errorMessage.value = '该输入端口已有普通连线，请先删除连线再公开为应用输入'
    return
  }
  const inputId = createUniquePublicId(`${node.node.node_id}_${port.name}`, new Set(templateInputs.value.map((input) => input.input_id)))
  const displayName = port.display_name || port.name
  const metadata = buildPublicPortMetadata(node, port)
  const required = options.required ?? port.required
  const templateInput: WorkflowGraphInput = {
    input_id: inputId,
    display_name: displayName,
    payload_type_id: port.payload_type_id,
    target_node_id: node.node.node_id,
    target_port: port.name,
    required,
    metadata,
  }
  const binding: FlowApplicationBinding = {
    binding_id: inputId,
    direction: 'input',
    template_port_id: inputId,
    binding_kind: 'api-request',
    required,
    config: { payload_type_id: port.payload_type_id },
    metadata,
  }
  templateInputs.value = [...templateInputs.value, templateInput]
  applicationBindingsDraft.value = [...applicationBindingsDraft.value, binding]
  setPreviewInputStateForBinding(binding)
  selectApplicationBoundary('entry')
  statusMessage.value = '已公开为应用输入'
  errorMessage.value = null
}

function exposeNodeOutputAsAppOutput(node: GraphNodeView, port: NodePortDefinition): void {
  if (!workflowApp.value) {
    errorMessage.value = '当前图还没有应用草稿，暂不能创建公开输出'
    return
  }
  const existingOutput = templateOutputs.value.find((output) => output.source_node_id === node.node.node_id && output.source_port === port.name)
  if (existingOutput) {
    selectApplicationBoundary('result')
    statusMessage.value = `${existingOutput.output_id} 已经是应用输出`
    return
  }
  const outputId = createDefaultPublicOutputId(node, port)
  const displayName = port.display_name || port.name
  const metadata = buildPublicPortMetadata(node, port)
  const templateOutput: WorkflowGraphOutput = {
    output_id: outputId,
    display_name: displayName,
    payload_type_id: port.payload_type_id,
    source_node_id: node.node.node_id,
    source_port: port.name,
    metadata,
  }
  const binding: FlowApplicationBinding = {
    binding_id: outputId,
    direction: 'output',
    template_port_id: outputId,
    binding_kind: 'http-response',
    required: false,
    config: { payload_type_id: port.payload_type_id },
    metadata,
  }
  templateOutputs.value = [...templateOutputs.value, templateOutput]
  applicationBindingsDraft.value = [...applicationBindingsDraft.value, binding]
  selectApplicationBoundary('result')
  statusMessage.value = '已公开为应用输出'
  errorMessage.value = null
}

function createDefaultPublicOutputId(node: GraphNodeView, port: NodePortDefinition): string {
  const shouldUseNodeId = node.node.node_type_id === 'core.output.http-response' && port.name === 'response'
  const baseValue = shouldUseNodeId ? node.node.node_id : `${node.node.node_id}_${port.name}`
  return createUniquePublicId(baseValue, new Set(templateOutputs.value.map((output) => output.output_id)))
}

function bindingEndpointText(binding: FlowApplicationBinding): string {
  const templatePort = readTemplatePortForBinding(binding)
  if (!templatePort) return '未找到 template port'
  if (binding.direction === 'input' && 'target_node_id' in templatePort) return `${templatePort.target_node_id}.${templatePort.target_port}`
  if (binding.direction === 'output' && 'source_node_id' in templatePort) return `${templatePort.source_node_id}.${templatePort.source_port}`
  return binding.template_port_id
}

function updateBindingIdFromEvent(binding: FlowApplicationBinding, event: Event): void {
  const target = event.target
  if (!(target instanceof HTMLInputElement)) return
  const oldBindingId = binding.binding_id
  const nextBindingId = normalizePublicIdentifier(target.value, oldBindingId)
  if (!renameApplicationBinding(binding, nextBindingId)) {
    target.value = oldBindingId
    errorMessage.value = `公开 id 已存在：${nextBindingId}`
    return
  }
  target.value = binding.binding_id
  statusMessage.value = '已更新公开 id'
  errorMessage.value = null
}

function updateBindingDisplayNameFromEvent(binding: FlowApplicationBinding, event: Event): void {
  const target = event.target
  if (!(target instanceof HTMLInputElement)) return
  const nextDisplayName = target.value.trim() || binding.binding_id
  setBindingDisplayName(binding, nextDisplayName)
  statusMessage.value = '已更新显示名称'
}

function updateBindingKindFromValue(binding: FlowApplicationBinding, value: SelectValue): void {
  const fallbackKind = binding.direction === 'input' ? 'api-request' : 'http-response'
  binding.binding_kind = selectValueToString(value).trim() || fallbackKind
  statusMessage.value = '已更新 binding kind'
}

function setPreviewImageRefTransportKind(bindingId: string, value: SelectValue): void {
  updatePreviewImageRefTransportKind(bindingId, value)
}

function updateBindingRequiredFromEvent(binding: FlowApplicationBinding, event: Event): void {
  const target = event.target
  if (!(target instanceof HTMLInputElement)) return
  updateApplicationBindingRequired(binding, target.checked)
  statusMessage.value = '已更新输入必填状态'
}

function deleteApplicationBinding(binding: FlowApplicationBinding): void {
  selectedBoundaryKind.value = deletePublicApplicationBinding(binding)
  statusMessage.value = '已删除公开接口'
  errorMessage.value = null
}

function deleteContextApplicationBinding(): void {
  const bindingId = contextMenu.value?.bindingId
  if (!bindingId) return
  const binding = applicationBindingsDraft.value.find((item) => item.binding_id === bindingId)
  if (!binding) return
  deleteApplicationBinding(binding)
  contextMenu.value = null
  nodePicker.value = null
}

function resetContextBoundaryPosition(): void {
  const boundaryKind = contextMenu.value?.boundaryKind ?? selectedBoundaryKind.value
  if (!boundaryKind) return
  resetBoundaryPosition(boundaryKind)
  selectApplicationBoundary(boundaryKind)
  statusMessage.value = '已重置边界位置'
}

function shouldIgnoreStagePointer(target: EventTarget | null): boolean {
  return target instanceof Element && Boolean(target.closest('.workflow-graph-node, .workflow-graph-boundary-node, .workflow-graph-floating-panel, .workflow-graph-minimap, .workflow-graph-minimap-toggle, .workflow-graph-context-menu, .workflow-node-picker, .workflow-graph-link, .workflow-graph-link-hit-area, .workflow-graph-link-handle, .workflow-graph-port'))
}

function shouldIgnoreStageWheelTarget(target: EventTarget | null): boolean {
  return target instanceof Element && Boolean(target.closest('input, textarea, select, button, .workflow-graph-floating-panel, .workflow-graph-minimap, .workflow-graph-minimap-toggle, .workflow-graph-context-menu, .workflow-node-picker, .image-viewer'))
}

function deleteSelectedNode(): void {
  const nodeId = selectedNodeId.value ?? contextMenu.value?.nodeId
  deleteGraphNode(nodeId)
}

function deleteSelectedEdge(): void {
  const edgeId = selectedEdgeId.value ?? contextMenu.value?.edgeId
  deleteGraphEdge(edgeId)
}

function openNodeContextMenu(event: MouseEvent, node: GraphNodeView): void {
  selectedNodeId.value = node.node.node_id
  selectedEdgeId.value = null
  selectedBoundaryKind.value = null
  const position = screenToWorld(event.clientX, event.clientY)
  nodePicker.value = null
  contextMenu.value = { x: event.clientX, y: event.clientY, worldX: position.x, worldY: position.y, nodeId: node.node.node_id, edgeId: null, port: null }
}

function openPortContextMenu(event: MouseEvent, node: GraphNodeView, port: NodePortDefinition, direction: PortDirection): void {
  selectedNodeId.value = node.node.node_id
  selectedEdgeId.value = null
  selectedBoundaryKind.value = null
  const position = screenToWorld(event.clientX, event.clientY)
  nodePicker.value = null
  contextMenu.value = {
    x: event.clientX,
    y: event.clientY,
    worldX: position.x,
    worldY: position.y,
    nodeId: node.node.node_id,
    edgeId: null,
    port: { nodeId: node.node.node_id, portName: port.name, direction },
  }
}

function openBoundaryContextMenu(event: MouseEvent, boundary: AppBoundaryNodeView): void {
  selectedBoundaryKind.value = boundary.kind
  selectedNodeId.value = null
  selectedEdgeId.value = null
  const position = screenToWorld(event.clientX, event.clientY)
  nodePicker.value = null
  contextMenu.value = { x: event.clientX, y: event.clientY, worldX: position.x, worldY: position.y, nodeId: null, edgeId: null, port: null, boundaryKind: boundary.kind, bindingId: null }
}

function openBoundaryPortContextMenu(event: MouseEvent, boundary: AppBoundaryNodeView, binding: FlowApplicationBinding): void {
  selectedBoundaryKind.value = boundary.kind
  selectedNodeId.value = null
  selectedEdgeId.value = null
  const position = screenToWorld(event.clientX, event.clientY)
  nodePicker.value = null
  contextMenu.value = { x: event.clientX, y: event.clientY, worldX: position.x, worldY: position.y, nodeId: null, edgeId: null, port: null, boundaryKind: boundary.kind, bindingId: binding.binding_id }
  statusMessage.value = `已选择 ${binding.binding_id}`
}

function openEdgeContextMenu(event: MouseEvent, link: GraphLinkView): void {
  if (!link.edge) return
  selectedEdgeId.value = link.edgeId
  selectedNodeId.value = null
  selectedBoundaryKind.value = null
  const position = screenToWorld(event.clientX, event.clientY)
  nodePicker.value = null
  contextMenu.value = { x: event.clientX, y: event.clientY, worldX: position.x, worldY: position.y, nodeId: null, edgeId: link.edgeId, port: null }
}

function openStageContextMenu(event: MouseEvent): void {
  if (shouldIgnoreStagePointer(event.target)) return
  const position = screenToWorld(event.clientX, event.clientY)
  nodePicker.value = null
  contextMenu.value = { x: event.clientX, y: event.clientY, worldX: position.x, worldY: position.y, nodeId: null, edgeId: null, port: null }
}

function calculateWorldBounds(): { minX: number; minY: number; maxX: number; maxY: number; width: number; height: number } {
  if (graphNodes.value.length === 0) {
    const viewLeft = -viewportX.value / viewportScale.value
    const viewTop = -viewportY.value / viewportScale.value
    const viewWidth = stageSize.value.width / viewportScale.value
    const viewHeight = stageSize.value.height / viewportScale.value
    return { minX: viewLeft, minY: viewTop, maxX: viewLeft + viewWidth, maxY: viewTop + viewHeight, width: viewWidth, height: viewHeight }
  }
  const boundaryNodes = appBoundaryNodes.value
  const minX = Math.min(...graphNodes.value.map((node) => node.x), ...boundaryNodes.map((boundary) => boundary.x)) - 160
  const minY = Math.min(...graphNodes.value.map((node) => node.y), ...boundaryNodes.map((boundary) => boundary.y)) - 120
  const maxX = Math.max(...graphNodes.value.map((node) => node.x + node.width), ...boundaryNodes.map((boundary) => boundary.x + boundary.width)) + 160
  const maxY = Math.max(...graphNodes.value.map((node) => node.y + nodeVisualHeight(node)), ...boundaryNodes.map((boundary) => boundary.y + boundaryNodeHeight(boundary))) + 120
  return { minX, minY, maxX, maxY, width: maxX - minX, height: maxY - minY }
}

function startMinimapNavigation(event: MouseEvent): void {
  moveViewportFromMinimap(event)
  document.addEventListener('mousemove', moveViewportFromMinimap)
  document.addEventListener('mouseup', stopMinimapNavigation)
}

function moveViewportFromMinimap(event: MouseEvent): void {
  const target = event.currentTarget instanceof Element ? event.currentTarget : document.querySelector('.workflow-graph-minimap')
  const bounds = target?.getBoundingClientRect()
  if (!bounds) return
  const scale = minimapScale.value
  const worldBoundsValue = worldBounds.value
  const worldX = worldBoundsValue.minX + (event.clientX - bounds.left - minimapPadding) / scale
  const worldY = worldBoundsValue.minY + (event.clientY - bounds.top - minimapPadding) / scale
  viewportX.value = stageSize.value.width / 2 - worldX * viewportScale.value
  viewportY.value = stageSize.value.height / 2 - worldY * viewportScale.value
}

function stopMinimapNavigation(): void {
  document.removeEventListener('mousemove', moveViewportFromMinimap)
  document.removeEventListener('mouseup', stopMinimapNavigation)
}

function fitView(): void {
  const bounds = worldBounds.value
  viewportX.value = stageSize.value.width / 2 - (bounds.minX + bounds.width / 2) * viewportScale.value
  viewportY.value = stageSize.value.height / 2 - (bounds.minY + bounds.height / 2) * viewportScale.value
  contextMenu.value = null
}

function focusGraphNode(nodeId: string): void {
  const graphNode = graphNodes.value.find((node) => node.node.node_id === nodeId)
  if (!graphNode) return
  selectNode(nodeId)
  const centerX = graphNode.x + graphNode.width / 2
  const centerY = graphNode.y + nodeVisualHeight(graphNode) / 2
  viewportX.value = stageSize.value.width / 2 - centerX * viewportScale.value
  viewportY.value = stageSize.value.height / 2 - centerY * viewportScale.value
}

function resetView(): void {
  viewportX.value = 0
  viewportY.value = 0
  viewportScale.value = 1
  contextMenu.value = null
}

function toggleMinimap(): void {
  minimapVisible.value = !minimapVisible.value
  contextMenu.value = null
}

function toggleGraphTheme(): void {
  preferencesStore.setTheme(graphTheme.value === 'dark' ? 'light' : 'dark')
  contextMenu.value = null
}

function previewBindingHelpText(binding: FlowApplicationBinding): string {
  const payloadTypeId = getBindingPayloadTypeId(binding) || 'unknown'
  const requiredText = binding.required ? '必填输入' : '可选输入'
  if (payloadTypeId === 'image-base64.v1') return `${requiredText}。选择图片文件后会自动转换为 image-base64 payload。`
  if (payloadTypeId === 'image-ref.v1') return `${requiredText}。可填写 ObjectStore object_key，或填写运行内存 image_handle。`
  if (payloadTypeId === 'value.v1') return `${requiredText}。按字段名和值提交 value payload。`
  return `${requiredText}。payload type: ${payloadTypeId}。`
}

function initializeWorkflowAppDrafts(appDocument: WorkflowAppDocument): void {
  templateInputs.value = appDocument.graphDocument.template.template_inputs.map((input) => ({ ...input, metadata: { ...input.metadata } }))
  templateOutputs.value = appDocument.graphDocument.template.template_outputs.map((output) => ({ ...output, metadata: { ...output.metadata } }))
  initializePublicBindings(appDocument)
  normalizeLoadedHttpResponseOutputIds(appDocument.graphDocument.template.nodes)
  normalizeLoadedRequestImageInputBindings()
  initializePreviewInputs(applicationBindingsDraft.value)
}

function normalizeLoadedHttpResponseOutputIds(nodes: WorkflowGraphNode[]): void {
  const nodeTypeById = new Map(nodes.map((node) => [node.node_id, node.node_type_id]))
  for (const output of templateOutputs.value) {
    if (nodeTypeById.get(output.source_node_id) !== 'core.output.http-response') continue
    if (output.source_port !== 'response') continue
    const legacyOutputId = normalizePublicIdentifier(`${output.source_node_id}_${output.source_port}`, output.output_id)
    if (output.output_id !== legacyOutputId) continue
    const existingIds = new Set([
      ...templateOutputs.value.filter((item) => item !== output).map((item) => item.output_id),
      ...applicationBindingsDraft.value
        .filter((binding) => binding.template_port_id !== output.output_id && binding.binding_id !== output.output_id)
        .map((binding) => binding.binding_id),
    ])
    const nextOutputId = createUniquePublicId(output.source_node_id, existingIds)
    if (nextOutputId === output.output_id) continue
    const previousOutputId = output.output_id
    output.output_id = nextOutputId
    for (const binding of applicationBindingsDraft.value) {
      if (binding.direction !== 'output' || binding.template_port_id !== previousOutputId) continue
      binding.template_port_id = nextOutputId
      if (binding.binding_id === previousOutputId) binding.binding_id = nextOutputId
    }
  }
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
  const draft = newWorkflowAppDraft.value
  return {
    ...sourceApplication,
    application_id: isNewApp.value ? draft.applicationId.trim() : sourceApplication.application_id,
    display_name: isNewApp.value ? draft.displayName.trim() : sourceApplication.display_name,
    template_ref: {
      ...sourceApplication.template_ref,
      template_id: template.template_id,
      template_version: template.template_version,
      source_kind: isNewApp.value ? 'json-file' : sourceApplication.template_ref.source_kind,
      source_uri: isNewApp.value
        ? buildWorkflowTemplateSourceUri(selectedProjectId.value, template.template_id, template.template_version)
        : sourceApplication.template_ref.source_uri,
    },
    description: isNewApp.value ? draft.description.trim() : sourceApplication.description,
    bindings: applicationBindingsDraft.value.map((binding) => ({
      ...binding,
      config: { ...binding.config },
      metadata: { ...binding.metadata },
    })),
    metadata: writeBoundaryPositionsToMetadata(sourceApplication.metadata),
  }
}

async function refreshSavedWorkflowApp(applicationId: string): Promise<void> {
  const previousNodeId = selectedNodeId.value
  const previousEdgeId = selectedEdgeId.value
  const previousBoundaryKind = selectedBoundaryKind.value
  const refreshedApp = await getWorkflowApp(selectedProjectId.value, applicationId)
  workflowApp.value = refreshedApp
  initializeWorkflowAppDrafts(refreshedApp)
  complexParameterDrafts.value = {}
  liteGraphAdapter.value?.loadTemplate(refreshedApp.graphDocument.template)
  graphEdges.value = refreshedApp.graphDocument.template.edges.map((edge) => ({ ...edge, metadata: { ...edge.metadata } }))
  graphNodes.value = buildGraphNodeViews(refreshedApp.graphDocument.template.nodes)
  if (previousBoundaryKind) {
    selectedBoundaryKind.value = previousBoundaryKind
    selectedNodeId.value = null
    selectedEdgeId.value = null
    return
  }
  selectedBoundaryKind.value = null
  selectedEdgeId.value = previousEdgeId && graphEdges.value.some((edge) => edge.edge_id === previousEdgeId) ? previousEdgeId : null
  selectedNodeId.value = selectedEdgeId.value
    ? null
    : previousNodeId && graphNodes.value.some((node) => node.node.node_id === previousNodeId)
      ? previousNodeId
      : graphNodes.value[0]?.node.node_id ?? null
}

function handleKeydown(event: KeyboardEvent): void {
  if ((event.key === 'Delete' || event.key === 'Backspace') && (selectedNodeId.value || selectedEdgeId.value)) {
    const target = event.target
    if (target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement || target instanceof HTMLSelectElement) return
    event.preventDefault()
    if (selectedNodeId.value) {
      deleteSelectedNode()
    } else {
      deleteSelectedEdge()
    }
  }
  if (event.key === 'Escape') {
    connectionDraft.value = null
    contextMenu.value = null
    errorMessage.value = null
  }
}

function updateStageSize(): void {
  const bounds = canvasRef.value?.getBoundingClientRect()
  if (!bounds) return
  stageSize.value = { width: bounds.width, height: bounds.height }
}

async function loadPage(): Promise<void> {
  loading.value = true
  clearActionMessages()
  resetPreviewRun()
  complexParameterDrafts.value = {}
  revokePreviewImageObjectUrls()
  try {
    nodeCatalog.value = await getWorkflowNodeCatalog()
    liteGraphAdapter.value = createWorkflowLiteGraphAdapter({ nodeDefinitions: nodeCatalog.value.node_definitions })
    if (!isNewApp.value && routeApplicationId.value) {
      workflowApp.value = await getWorkflowApp(selectedProjectId.value, routeApplicationId.value)
      initializeWorkflowAppDrafts(workflowApp.value)
      liteGraphAdapter.value.loadTemplate(workflowApp.value.graphDocument.template)
      graphEdges.value = workflowApp.value.graphDocument.template.edges.map((edge) => ({ ...edge, metadata: { ...edge.metadata } }))
      graphNodes.value = buildGraphNodeViews(workflowApp.value.graphDocument.template.nodes)
      selectedNodeId.value = graphNodes.value[0]?.node.node_id ?? null
      selectedEdgeId.value = null
      selectedBoundaryKind.value = null
    } else {
      newWorkflowAppDraft.value = createNewWorkflowAppDraftState()
      workflowApp.value = createLocalWorkflowAppDraft()
      initializeWorkflowAppDrafts(workflowApp.value)
      liteGraphAdapter.value.loadTemplate(workflowApp.value.graphDocument.template)
      graphEdges.value = []
      graphNodes.value = []
      selectedNodeId.value = null
      selectedEdgeId.value = null
      selectedBoundaryKind.value = null
    }
    await nextTick()
    updateStageSize()
    if (graphNodes.value.length > 0) {
      fitView()
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : t('workflowEditor.messages.loadFailed')
  } finally {
    loading.value = false
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
