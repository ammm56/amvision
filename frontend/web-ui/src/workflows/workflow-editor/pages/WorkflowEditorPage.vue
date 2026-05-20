<template>
  <section class="workflow-graph-workbench" :class="`workflow-graph-workbench--${graphTheme}`">
    <header class="workflow-graph-toolbar">
      <div class="workflow-graph-toolbar__title">
        <RouterLink to="/workflows/apps" class="workflow-graph-toolbar__back">
          <ArrowLeft :size="16" />
          {{ t('workflowEditor.actions.backToApps') }}
        </RouterLink>
        <div>
          <p>{{ t('workflowEditor.editor.kicker') }}</p>
          <h1>{{ editorTitle }}</h1>
        </div>
      </div>
      <div class="workflow-graph-toolbar__meta">
        <span>{{ t('workflowEditor.fields.nodeCount') }} {{ graphNodes.length }}</span>
        <span>{{ t('workflowEditor.fields.edgeCount') }} {{ graphLinks.length }}</span>
        <span>{{ workflowApp?.primaryRuntime?.observed_state ?? t('common.none') }}</span>
        <span v-if="lastPreviewRun">Preview {{ lastPreviewRun.state }}</span>
        <span v-if="statusMessage">{{ statusMessage }}</span>
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
        <Button variant="secondary" :disabled="previewing || !workflowApp" @click="runPreview">
          <Play :size="16" />
          {{ t('workflowEditor.actions.previewRun') }}
        </Button>
        <Button variant="primary" :disabled="saving || !workflowApp" @click="saveCurrentWorkflowApp">
          <Save :size="16" />
          {{ t('workflowEditor.actions.saveWorkflowApp') }}
        </Button>
      </div>
    </header>

    <div
      ref="canvasRef"
      class="workflow-graph-stage"
      @dragover.prevent
      @drop="dropPaletteNode"
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
            @click.stop="selectEdge(link.edgeId)"
            @contextmenu.prevent.stop="openEdgeContextMenu($event, link)"
          />
          <path
            v-for="link in graphLinks"
            :key="link.edgeId"
            class="workflow-graph-link"
            :class="{ 'is-selected': selectedEdgeId === link.edgeId }"
            :d="linkPath(link)"
            @click.stop="selectEdge(link.edgeId)"
            @contextmenu.prevent.stop="openEdgeContextMenu($event, link)"
          />
          <circle
            v-for="marker in graphLinkMidpoints"
            :key="`${marker.edgeId}-midpoint`"
            class="workflow-graph-link-midpoint"
            :class="{ 'is-selected': selectedEdgeId === marker.edgeId }"
            :cx="marker.x"
            :cy="marker.y"
            r="4.5"
            @click.stop="selectEdge(marker.edgeId)"
            @contextmenu.prevent.stop="openEdgeContextMenu($event, marker.link)"
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
          :class="[`workflow-graph-boundary-node--${boundary.kind}`, { 'is-selected': selectedBoundaryKind === boundary.kind }]"
          :style="{ left: `${boundary.x}px`, top: `${boundary.y}px`, width: `${boundary.width}px` }"
          @click.stop="selectApplicationBoundary(boundary.kind)"
        >
          <span class="workflow-graph-boundary-node__title">{{ boundary.title }}</span>
          <span class="workflow-graph-boundary-node__type">{{ boundary.description }}</span>
          <span v-for="binding in boundary.bindings" :key="`${boundary.id}-${binding.binding_id}`" class="workflow-graph-boundary-binding">
            <strong>{{ binding.binding_id }}</strong>
            <small>{{ getBindingPayloadTypeId(binding) || 'unknown' }}</small>
          </span>
        </div>

        <div
          v-for="node in graphNodes"
          :key="node.node.node_id"
          role="button"
          tabindex="0"
          class="workflow-graph-node"
          :class="{ 'is-selected': selectedNodeId === node.node.node_id }"
          :style="{ left: `${node.x}px`, top: `${node.y}px`, width: `${node.width}px`, height: `${nodeVisualHeight(node)}px` }"
          @mousedown.stop="startNodeDrag($event, node)"
          @click.stop="handleNodeClick(node.node.node_id)"
          @contextmenu.prevent.stop="openNodeContextMenu($event, node)"
        >
          <span class="workflow-graph-node__title">{{ node.title }}</span>
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
              >
                <span class="workflow-graph-port__dot" aria-hidden="true" />
                <span class="workflow-graph-port__label">{{ row.input.display_name || row.input.name }}</span>
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
              >
                <span class="workflow-graph-port__label">{{ row.output.display_name || row.output.name }}</span>
                <span class="workflow-graph-port__dot" aria-hidden="true" />
              </span>
              <span v-else class="workflow-graph-port workflow-graph-port--placeholder" />
            </div>
          </div>
          <div v-if="nodeParameterFieldsForNode(node).length" class="workflow-graph-node-widgets">
            <label
              v-for="field in nodeParameterFieldsForNode(node).slice(0, 4)"
              :key="`${node.node.node_id}-${field.parameter_name}`"
              class="workflow-graph-node-widget"
              @mousedown.stop
              @click.stop
            >
              <span>{{ field.display_name }}</span>
              <select
                v-if="field.enum_options.length"
                :value="readNodeParameterEnumIndex(node, field)"
                :disabled="field.readonly"
                @change="updateNodeParameterFromEnumEvent(node, field, $event)"
              >
                <option v-if="!field.required" value="">未设置</option>
                <option v-for="(option, index) in field.enum_options" :key="`${field.parameter_name}-${index}`" :value="String(index)">
                  {{ option.label }}
                </option>
              </select>
              <input
                v-else-if="isBooleanParameter(field)"
                type="checkbox"
                :checked="readNodeParameterBooleanValue(node, field)"
                :disabled="field.readonly"
                @change="updateNodeParameterFromCheckboxEvent(node, field, $event)"
              />
              <input
                v-else-if="isNumberParameter(field)"
                type="number"
                step="any"
                :value="readNodeParameterTextValue(node, field)"
                :disabled="field.readonly"
                @change="updateNodeParameterFromNumberEvent(node, field, $event)"
              />
              <input
                v-else-if="isStringParameter(field)"
                :value="readNodeParameterTextValue(node, field)"
                :disabled="field.readonly"
                @input="updateNodeParameterFromTextEvent(node, field, $event)"
              />
              <small v-else>高级参数</small>
            </label>
          </div>
          <div
            v-if="getPreviewNodeImage(node.node.node_id)"
            class="workflow-graph-node-preview"
            title="双击查看原图"
            @mousedown.stop
            @dblclick.stop="openImageViewer(getPreviewNodeImage(node.node.node_id))"
          >
            <img
              v-if="getPreviewNodeImage(node.node.node_id)?.src"
              :src="getPreviewNodeImage(node.node.node_id)?.src || ''"
              :alt="getPreviewNodeImage(node.node.node_id)?.title || node.title"
              draggable="false"
            />
            <span v-else>{{ getPreviewNodeImage(node.node.node_id)?.statusText }}</span>
            <small>{{ getPreviewNodeImage(node.node.node_id)?.title }}</small>
          </div>
        </div>
      </div>

      <button
        type="button"
        class="workflow-graph-palette-toggle"
        :class="{ 'workflow-graph-palette-toggle--open': !paletteCollapsed }"
        @click.stop="paletteCollapsed = !paletteCollapsed"
      >
        <PanelLeftOpen v-if="paletteCollapsed" :size="17" />
        <PanelLeftClose v-else :size="17" />
        <span>{{ t('workflowEditor.actions.toggleNodePalette') }}</span>
      </button>

      <aside v-if="!paletteCollapsed" class="workflow-graph-floating-panel workflow-graph-palette-panel" @mousedown.stop @contextmenu.stop>
        <div class="workflow-graph-panel__header">
          <div>
            <p>{{ t('workflowEditor.catalog.kicker') }}</p>
            <h2>{{ t('workflowEditor.catalog.paletteTitle') }}</h2>
          </div>
          <StatusBadge tone="info">{{ nodeCatalog?.node_definitions.length ?? 0 }}</StatusBadge>
        </div>
        <div class="workflow-graph-palette-sections">
          <section v-for="section in paletteSections" :key="section.id" class="workflow-graph-palette-section">
            <div class="workflow-graph-palette-section__title">
              <strong>{{ section.title }}</strong>
              <span>{{ section.nodeCount }}</span>
            </div>
            <EmptyState v-if="section.nodeCount === 0" :title="section.emptyTitle" :description="section.emptyDescription" />
            <details v-for="group in section.groups" v-else :key="`${section.id}-${group.category}`" open class="workflow-graph-node-group">
              <summary>
                <span>{{ group.displayName }}</span>
                <strong>{{ group.nodes.length }}</strong>
              </summary>
              <button
                v-for="definition in group.nodes"
                :key="definition.node_type_id"
                type="button"
                draggable="true"
                class="workflow-graph-palette-node"
                @dragstart="startPaletteDrag($event, definition)"
              >
                <strong>{{ definition.display_name }}</strong>
                <span>{{ definition.node_type_id }}</span>
              </button>
            </details>
          </section>
        </div>
      </aside>

      <aside class="workflow-graph-floating-panel workflow-graph-inspector-panel" @mousedown.stop @contextmenu.stop>
        <div class="workflow-graph-panel__header">
          <div>
            <p>{{ t('workflowEditor.editor.inspectorKicker') }}</p>
            <h2>{{ t('workflowEditor.editor.inspectorTitle') }}</h2>
          </div>
          <StatusBadge tone="neutral">Inspector</StatusBadge>
        </div>
        <div v-if="workflowApp" class="workflow-graph-app-contract">
          <div class="workflow-graph-panel__header workflow-graph-panel__header--compact">
            <div>
              <p>Application</p>
              <h2>应用入口</h2>
            </div>
            <StatusBadge tone="info">{{ appInputBindings.length }} / {{ appOutputBindings.length }}</StatusBadge>
          </div>
          <section class="workflow-graph-contract-section">
            <h3>应用输入</h3>
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
        <div v-if="selectedNode" class="workflow-graph-inspector-body">
          <div class="workflow-graph-inspector-row">
            <span>{{ t('workflowEditor.columns.application') }}</span>
            <strong>{{ selectedNode.title }}</strong>
          </div>
          <div class="workflow-graph-inspector-row">
            <span>Node type</span>
            <strong>{{ selectedNode.node.node_type_id }}</strong>
          </div>
          <div v-if="selectedPreviewNodeImage" class="workflow-graph-preview-card">
            <img
              v-if="selectedPreviewNodeImage.src"
              :src="selectedPreviewNodeImage.src"
              :alt="selectedPreviewNodeImage.title"
              draggable="false"
              title="双击查看原图"
              @dblclick.stop="openImageViewer(selectedPreviewNodeImage)"
            />
            <div v-else class="workflow-graph-preview-card__empty">{{ selectedPreviewNodeImage.statusText }}</div>
            <div class="workflow-graph-preview-card__meta">
              <strong>{{ selectedPreviewNodeImage.title }}</strong>
              <span>{{ selectedPreviewNodeImage.transportKind }} / {{ selectedPreviewNodeImage.mediaType || 'unknown' }}</span>
              <span v-if="selectedPreviewNodeImage.width || selectedPreviewNodeImage.height">
                {{ selectedPreviewNodeImage.width || '-' }} × {{ selectedPreviewNodeImage.height || '-' }}
              </span>
            </div>
            <Button v-if="selectedPreviewNodeImage.src" size="sm" variant="secondary" type="button" @click="openImageViewer(selectedPreviewNodeImage)">
              查看原图
            </Button>
          </div>
          <div v-if="selectedNodeParameterFields.length" class="workflow-graph-parameter-panel">
            <div class="workflow-graph-panel__header workflow-graph-panel__header--compact">
              <div>
                <p>Parameters</p>
                <h2>节点参数</h2>
              </div>
              <StatusBadge tone="info">{{ selectedNodeParameterFields.length }}</StatusBadge>
            </div>
            <label
              v-for="field in selectedNodeParameterFields"
              :key="`inspector-${selectedNode.node.node_id}-${field.parameter_name}`"
              class="workflow-graph-parameter-field"
            >
              <div class="workflow-graph-parameter-field__label">
                <span>{{ field.display_name }}</span>
                <button
                  v-if="parameterHelpText(field)"
                  type="button"
                  class="workflow-graph-help-icon"
                  :title="parameterHelpText(field)"
                  :aria-label="parameterHelpText(field)"
                >
                  <CircleAlert :size="13" />
                </button>
              </div>
              <select
                v-if="field.enum_options.length"
                :value="readNodeParameterEnumIndex(selectedNode, field)"
                :disabled="field.readonly"
                @change="updateNodeParameterFromEnumEvent(selectedNode, field, $event)"
              >
                <option v-if="!field.required" value="">未设置</option>
                <option v-for="(option, index) in field.enum_options" :key="`inspector-${field.parameter_name}-${index}`" :value="String(index)">
                  {{ option.label }}
                </option>
              </select>
              <input
                v-else-if="isBooleanParameter(field)"
                type="checkbox"
                :checked="readNodeParameterBooleanValue(selectedNode, field)"
                :disabled="field.readonly"
                @change="updateNodeParameterFromCheckboxEvent(selectedNode, field, $event)"
              />
              <input
                v-else-if="isNumberParameter(field)"
                type="number"
                step="any"
                :value="readNodeParameterTextValue(selectedNode, field)"
                :disabled="field.readonly"
                @change="updateNodeParameterFromNumberEvent(selectedNode, field, $event)"
              />
              <input
                v-else-if="isStringParameter(field)"
                :value="readNodeParameterTextValue(selectedNode, field)"
                :disabled="field.readonly"
                @input="updateNodeParameterFromTextEvent(selectedNode, field, $event)"
              />
              <div v-else class="workflow-graph-parameter-field__unsupported">复杂参数后续用专用控件编辑</div>
            </label>
          </div>
          <div class="workflow-graph-inspector-row">
            <span>{{ t('workflowEditor.fields.payloadTypes') }}</span>
            <strong>{{ selectedNode.inputs.length }} / {{ selectedNode.outputs.length }}</strong>
          </div>
        </div>
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
        <div v-else-if="workflowApp" class="workflow-graph-inspector-body">
          <div class="workflow-graph-inspector-row">
            <span>{{ t('workflowEditor.columns.application') }}</span>
            <strong>{{ workflowApp.applicationDocument.application_id }}</strong>
          </div>
          <div class="workflow-graph-inspector-row">
            <span>{{ t('workflowEditor.fields.templateInputs') }}</span>
            <strong>{{ workflowApp.graphDocument.template_input_ids.join(', ') || t('common.noValue') }}</strong>
          </div>
          <div class="workflow-graph-inspector-row">
            <span>{{ t('workflowEditor.fields.templateOutputs') }}</span>
            <strong>{{ workflowApp.graphDocument.template_output_ids.join(', ') || t('common.noValue') }}</strong>
          </div>
          <div v-if="lastPreviewRun" class="workflow-graph-inspector-row">
            <span>Preview run</span>
            <strong>{{ lastPreviewRun.preview_run_id }} / {{ lastPreviewRun.state }}</strong>
          </div>
        </div>
        <EmptyState v-else :title="t('workflowEditor.editor.emptyInspectorTitle')" :description="t('workflowEditor.editor.emptyInspectorDescription')" />

        <div v-if="workflowApp" class="workflow-graph-preview-inputs">
          <div class="workflow-graph-panel__header">
            <div>
              <p>Preview</p>
              <h2>Preview 输入</h2>
            </div>
            <div class="workflow-graph-panel__tools">
              <button
                v-if="previewHelpText"
                type="button"
                class="workflow-graph-help-icon"
                :title="previewHelpText"
                :aria-label="previewHelpText"
              >
                <CircleAlert :size="14" />
              </button>
              <StatusBadge :tone="previewBlockingMessages.length ? 'danger' : 'success'">
                {{ previewBlockingMessages.length ? '缺少输入' : '就绪' }}
              </StatusBadge>
            </div>
          </div>
          <section v-for="binding in previewInputBindings" :key="binding.binding_id" class="workflow-graph-preview-binding">
            <div class="workflow-graph-preview-binding__header">
              <span>
                <strong>{{ binding.binding_id }}</strong>
                <small>{{ getBindingPayloadTypeId(binding) || 'unknown' }}</small>
              </span>
              <div class="workflow-graph-preview-binding__tools">
                <button
                  type="button"
                  class="workflow-graph-help-icon"
                  :title="previewBindingHelpText(binding)"
                  :aria-label="previewBindingHelpText(binding)"
                >
                  <CircleAlert :size="13" />
                </button>
                <StatusBadge :tone="binding.required ? 'warning' : 'neutral'">{{ binding.required ? '必填' : '可选' }}</StatusBadge>
              </div>
            </div>
            <template v-if="previewInputState[binding.binding_id] && getBindingPayloadTypeId(binding) === 'value.v1'">
              <div class="workflow-graph-value-fields">
                <label v-for="field in previewInputState[binding.binding_id].valueFields" :key="field.id" class="workflow-graph-value-field">
                  <input v-model="field.key" placeholder="字段名" />
                  <input v-model="field.value" placeholder="字段值" />
                  <button type="button" title="删除字段" @click="removePreviewValueField(binding.binding_id, field.id)">
                    <Trash2 :size="14" />
                  </button>
                </label>
              </div>
              <Button size="sm" variant="secondary" type="button" @click="addPreviewValueField(binding.binding_id)">
                <Plus :size="14" />
                添加字段
              </Button>
            </template>
            <template v-else-if="previewInputState[binding.binding_id] && getBindingPayloadTypeId(binding) === 'image-base64.v1'">
              <FilePicker
                v-model="previewInputState[binding.binding_id].file"
                icon="image"
                accept="image/*"
                label="图片文件"
              />
              <label class="workflow-graph-preview-field">
                <span>media_type</span>
                <input v-model="previewInputState[binding.binding_id].mediaType" placeholder="自动使用文件类型" />
              </label>
            </template>
            <template v-else-if="previewInputState[binding.binding_id] && getBindingPayloadTypeId(binding) === 'image-ref.v1'">
              <label class="workflow-graph-preview-field">
                <span>引用来源</span>
                <select v-model="previewInputState[binding.binding_id].imageRefTransportKind">
                  <option value="storage">ObjectStore 图片</option>
                  <option value="memory">运行内存 image handle</option>
                </select>
              </label>
              <label v-if="previewInputState[binding.binding_id].imageRefTransportKind === 'storage'" class="workflow-graph-preview-field">
                <span>object_key</span>
                <input v-model="previewInputState[binding.binding_id].objectKey" placeholder="project/files/image.jpg" />
              </label>
              <label v-else class="workflow-graph-preview-field">
                <span>image_handle</span>
                <input v-model="previewInputState[binding.binding_id].imageHandle" placeholder="execution-scoped image handle" />
              </label>
              <label class="workflow-graph-preview-field">
                <span>media_type</span>
                <input v-model="previewInputState[binding.binding_id].mediaType" placeholder="image/jpeg" />
              </label>
            </template>
            <template v-else-if="previewInputState[binding.binding_id]">
              <label class="workflow-graph-preview-field">
                <span>输入值</span>
                <input v-model="previewInputState[binding.binding_id].plainValue" placeholder="按字符串值提交" />
              </label>
            </template>
          </section>
        </div>
      </aside>

      <div v-if="minimapVisible" class="workflow-graph-minimap" @mousedown.stop="startMinimapNavigation" @contextmenu.stop>
        <button
          type="button"
          class="workflow-graph-minimap__close"
          title="隐藏小地图"
          aria-label="隐藏小地图"
          @mousedown.stop
          @click.stop="toggleMinimap"
        >
          <X :size="14" />
        </button>
        <div class="workflow-graph-minimap__nodes">
          <span
            v-for="miniNode in minimapNodes"
            :key="miniNode.nodeId"
            class="workflow-graph-minimap__node"
            :class="{ 'is-selected': miniNode.nodeId === selectedNodeId }"
            :style="miniNode.style"
          />
          <span class="workflow-graph-minimap__viewport" :style="minimapViewportStyle" />
        </div>
      </div>
      <button
        v-else
        type="button"
        class="workflow-graph-minimap-toggle"
        title="显示小地图"
        aria-label="显示小地图"
        @mousedown.stop
        @click.stop="toggleMinimap"
      >
        <MapIcon :size="16" />
      </button>

      <div v-if="contextMenu" class="workflow-graph-context-menu" :style="contextMenuStyle" @mousedown.stop @contextmenu.prevent>
        <button v-if="contextMenu.nodeId" type="button" @click="deleteSelectedNode">
          <Trash2 :size="15" />
          删除节点
        </button>
        <button v-if="contextMenu.edgeId" type="button" @click="deleteSelectedEdge">
          <Trash2 :size="15" />
          删除连线
        </button>
        <button type="button" @click="fitView">
          <MapIcon :size="15" />
          定位全部节点
        </button>
        <button type="button" @click="resetView">
          <RefreshCw :size="15" />
          重置画布位置
        </button>
        <button type="button" @click="toggleMinimap">
          <MapIcon :size="15" />
          {{ minimapVisible ? '隐藏小地图' : '显示小地图' }}
        </button>
        <button type="button" @click="toggleGraphTheme">
          <Sun v-if="graphTheme === 'dark'" :size="15" />
          <Moon v-else :size="15" />
          {{ graphTheme === 'dark' ? t('preferences.light') : t('preferences.dark') }}
        </button>
        <button type="button" :disabled="!workflowApp || saving" @click="saveCurrentWorkflowApp">
          <Save :size="15" />
          {{ t('workflowEditor.actions.saveWorkflowApp') }}
        </button>
        <button type="button" :disabled="!workflowApp || previewing" @click="runPreview">
          <Play :size="15" />
          {{ t('workflowEditor.actions.previewRun') }}
        </button>
      </div>

      <div v-if="!loading && graphNodes.length === 0" class="workflow-graph-empty">
        <Workflow :size="42" />
        <strong>{{ t('workflowEditor.editor.canvasPlaceholderTitle') }}</strong>
        <span>{{ t('workflowEditor.editor.canvasPlaceholderDescription') }}</span>
      </div>
    </div>
    <ImageViewer :open="Boolean(activeImageViewer)" :image="activeImageViewer" @close="activeImageViewer = null" />
  </section>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, shallowRef } from 'vue'
import { ArrowLeft, CircleAlert, Map as MapIcon, Moon, PanelLeftClose, PanelLeftOpen, Play, Plus, RefreshCw, Save, Sun, Trash2, Workflow, X } from '@lucide/vue'
import { RouterLink, useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'

import { usePreferencesStore } from '@/app/stores/preferences.store'
import { useProjectStore } from '@/app/stores/project.store'
import Button from '@/shared/ui/components/Button.vue'
import FilePicker from '@/shared/ui/components/FilePicker.vue'
import ImageViewer from '@/shared/ui/components/ImageViewer.vue'
import StatusBadge from '@/shared/ui/data-display/StatusBadge.vue'
import EmptyState from '@/shared/ui/feedback/EmptyState.vue'
import InlineError from '@/shared/ui/feedback/InlineError.vue'
import { createWorkflowLiteGraphAdapter, type WorkflowLiteGraphAdapter } from '../canvas/graph-engine/litegraph-adapter'
import { type WorkflowCanvasGraphSnapshot } from '../canvas/graph-engine/workflow-graph-conversion'
import { getWorkflowNodeCatalog } from '../services/node-catalog.service'
import { getWorkflowApp, saveWorkflowApp, type WorkflowAppDocument } from '../services/workflow-app.service'
import { createWorkflowPreviewRun, readProjectObjectContentBlob, readWorkflowPreviewRunArtifactBlob } from '../services/workflow-runtime.service'
import type { FlowApplicationBinding, NodeDefinition, NodeParameterUiField, NodePortDefinition, WorkflowGraphEdge, WorkflowGraphNode, WorkflowJsonObject, WorkflowNodeCatalogResponse, WorkflowPreviewDisplayOutput, WorkflowPreviewRun } from '../types'

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

interface GraphLinkView {
  edgeId: string
  edge: WorkflowGraphEdge
  sourceX: number
  sourceY: number
  targetX: number
  targetY: number
}

interface DragState {
  nodeId: string
  offsetX: number
  offsetY: number
}

type PortDirection = 'input' | 'output'

interface PortReference {
  nodeId: string
  portName: string
  direction: PortDirection
}

interface ConnectionDraftState {
  anchorDirection: PortDirection
  anchorNodeId: string
  anchorPort: string
  anchorX: number
  anchorY: number
  pointerX: number
  pointerY: number
  startClientX: number
  startClientY: number
  hasMoved: boolean
  replacingEdgeId?: string | null
}

interface PanState {
  startClientX: number
  startClientY: number
  startX: number
  startY: number
}

interface PaletteGroup {
  category: string
  displayName: string
  nodes: NodeDefinition[]
}

interface PaletteSection {
  id: 'core' | 'custom'
  title: string
  emptyTitle: string
  emptyDescription: string
  nodeCount: number
  groups: PaletteGroup[]
}

interface ContextMenuState {
  x: number
  y: number
  nodeId: string | null
  edgeId: string | null
}

interface MinimapNodeView {
  nodeId: string
  style: Record<string, string>
}

interface AppBoundaryNodeView {
  id: string
  kind: 'entry' | 'result'
  title: string
  description: string
  x: number
  y: number
  width: number
  bindings: FlowApplicationBinding[]
}

interface PreviewValueField {
  id: string
  key: string
  value: string
}

interface PreviewInputState {
  valueFields: PreviewValueField[]
  file: File | null
  mediaType: string
  imageRefTransportKind: 'storage' | 'memory'
  objectKey: string
  imageHandle: string
  plainValue: string
}

interface PreviewNodeImageView {
  nodeId: string
  title: string
  src: string | null
  statusText: string
  transportKind: string
  mediaType: string
  width: number | null
  height: number | null
  objectKey: string | null
}

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

const { t } = useI18n()
const route = useRoute()
const preferencesStore = usePreferencesStore()
const projectStore = useProjectStore()

const loading = ref(false)
const saving = ref(false)
const previewing = ref(false)
const errorMessage = ref<string | null>(null)
const statusMessage = ref<string | null>(null)
const nodeCatalog = ref<WorkflowNodeCatalogResponse | null>(null)
const workflowApp = ref<WorkflowAppDocument | null>(null)
const graphNodes = ref<GraphNodeView[]>([])
const graphEdges = ref<WorkflowGraphEdge[]>([])
const selectedNodeId = ref<string | null>(null)
const selectedEdgeId = ref<string | null>(null)
const selectedBoundaryKind = ref<'entry' | 'result' | null>(null)
const dragState = ref<DragState | null>(null)
const connectionDraft = ref<ConnectionDraftState | null>(null)
const panState = ref<PanState | null>(null)
const suppressNextNodeClick = ref(false)
const pendingPaletteNodeTypeId = ref<string | null>(null)
const paletteCollapsed = ref(false)
const minimapVisible = ref(true)
const contextMenu = ref<ContextMenuState | null>(null)
const previewInputState = ref<Record<string, PreviewInputState>>({})
const viewportX = ref(0)
const viewportY = ref(0)
const viewportScale = ref(1)
const stageSize = ref({ width: 1, height: 1 })
const lastPreviewRun = ref<WorkflowPreviewRun | null>(null)
const previewNodeImages = ref<Record<string, PreviewNodeImageView>>({})
const activeImageViewer = ref<PreviewNodeImageView | null>(null)
const canvasRef = ref<HTMLElement | null>(null)
const liteGraphAdapter = shallowRef<WorkflowLiteGraphAdapter | null>(null)
let resizeObserver: ResizeObserver | null = null
let previewImageObjectUrls: string[] = []

const minimapWidth = 184
const minimapHeight = 116
const minimapPadding = 10
const graphNodeHeaderHeight = 62
const graphPortRowHeight = 28
const graphPortInsetX = 17
const graphNodeWidgetRowHeight = 34
const graphNodePreviewHeight = 138
const minViewportScale = 0.35
const maxViewportScale = 2.4

const selectedProjectId = computed(() => projectStore.selectedProjectId)
const routeApplicationId = computed(() => (typeof route.params.applicationId === 'string' ? route.params.applicationId : ''))
const isNewApp = computed(() => route.path.endsWith('/new'))
const graphTheme = computed(() => preferencesStore.theme)
const nodeDefinitionsById = computed(() => new Map((nodeCatalog.value?.node_definitions ?? []).map((definition) => [definition.node_type_id, definition])))
const editorTitle = computed(() => workflowApp.value?.applicationDocument.application.display_name || (isNewApp.value ? t('workflowEditor.editor.newTitle') : routeApplicationId.value))
const selectedNode = computed(() => graphNodes.value.find((node) => node.node.node_id === selectedNodeId.value) ?? null)
const selectedPreviewNodeImage = computed(() => selectedNode.value ? previewNodeImages.value[selectedNode.value.node.node_id] ?? null : null)
const selectedEdge = computed(() => graphEdges.value.find((edge) => edge.edge_id === selectedEdgeId.value) ?? null)
const selectedNodeParameterFields = computed(() => nodeParameterFieldsForNode(selectedNode.value))
const graphLinkMidpoints = computed<EdgeHandleView[]>(() => graphLinks.value.map((link) => ({
  key: `${link.edgeId}-midpoint`,
  edgeId: link.edgeId,
  link,
  ...linkPointAt(link, 0.5),
})))
const selectedEdgeReconnectHandles = computed<EdgeHandleView[]>(() => {
  const link = graphLinks.value.find((item) => item.edgeId === selectedEdgeId.value)
  if (!link) return []
  return [{ key: `${link.edgeId}-reconnect`, edgeId: link.edgeId, link, ...linkPointAt(link, 0.5) }]
})
const applicationBindings = computed(() => workflowApp.value?.applicationDocument.application.bindings ?? [])
const appInputBindings = computed(() => applicationBindings.value.filter((binding) => binding.direction === 'input'))
const appOutputBindings = computed(() => applicationBindings.value.filter((binding) => binding.direction === 'output'))
const templateInputById = computed(() => new Map((workflowApp.value?.graphDocument.template.template_inputs ?? []).map((input) => [input.input_id, input])))
const templateOutputById = computed(() => new Map((workflowApp.value?.graphDocument.template.template_outputs ?? []).map((output) => [output.output_id, output])))
const graphLinks = computed(() => buildGraphLinks(graphEdges.value))
const draftLinkPath = computed(() => connectionDraft.value ? linkPath(buildDraftLink(connectionDraft.value)) : '')
const worldTransformStyle = computed(() => ({
  transform: `translate(${viewportX.value}px, ${viewportY.value}px) scale(${viewportScale.value})`,
}))
const contextMenuStyle = computed(() => contextMenu.value ? { left: `${contextMenu.value.x}px`, top: `${contextMenu.value.y}px` } : {})
const worldBounds = computed(() => calculateWorldBounds())
const minimapScale = computed(() => {
  const bounds = worldBounds.value
  const availableWidth = minimapWidth - minimapPadding * 2
  const availableHeight = minimapHeight - minimapPadding * 2
  return Math.min(availableWidth / Math.max(bounds.width, 1), availableHeight / Math.max(bounds.height, 1))
})
const minimapNodes = computed<MinimapNodeView[]>(() => graphNodes.value.map((node) => {
  const bounds = worldBounds.value
  const scale = minimapScale.value
  return {
    nodeId: node.node.node_id,
    style: {
      left: `${minimapPadding + (node.x - bounds.minX) * scale}px`,
      top: `${minimapPadding + (node.y - bounds.minY) * scale}px`,
      width: `${Math.max(node.width * scale, 8)}px`,
      height: `${Math.max(72 * scale, 5)}px`,
    },
  }
}))
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
const paletteSections = computed<PaletteSection[]>(() => {
  const definitions = nodeCatalog.value?.node_definitions ?? []
  const coreDefinitions = definitions.filter((definition) => definition.implementation_kind === 'core-node')
  const customDefinitions = definitions.filter((definition) => definition.implementation_kind === 'custom-node')
  return [
    {
      id: 'core',
      title: t('workflowEditor.palette.coreNodes'),
      emptyTitle: t('workflowEditor.palette.emptyCoreTitle'),
      emptyDescription: t('workflowEditor.palette.emptyCoreDescription'),
      nodeCount: coreDefinitions.length,
      groups: groupDefinitionsByCategory(coreDefinitions),
    },
    {
      id: 'custom',
      title: t('workflowEditor.palette.customNodes'),
      emptyTitle: t('workflowEditor.palette.emptyCustomTitle'),
      emptyDescription: t('workflowEditor.palette.emptyCustomDescription'),
      nodeCount: customDefinitions.length,
      groups: groupDefinitionsByCategory(customDefinitions),
    },
  ]
})
const appBoundaryNodes = computed<AppBoundaryNodeView[]>(() => buildAppBoundaryNodes())
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
const missingRequiredPreviewBindingIds = computed(() => previewInputBindings.value
  .filter((binding) => binding.required && !hasPreviewBindingValue(binding))
  .map((binding) => binding.binding_id))
const missingAlternativePreviewBindingGroups = computed(() => {
  if (previewAlternativeImageBindingIds.value.length < 2) return []
  const hasAnyImageInput = previewAlternativeImageBindingIds.value.some((bindingId) => {
    const binding = previewInputBindings.value.find((item) => item.binding_id === bindingId)
    return binding ? hasPreviewBindingValue(binding) : false
  })
  return hasAnyImageInput ? [] : [previewAlternativeImageBindingIds.value]
})
const previewBlockingMessages = computed(() => {
  const messages: string[] = []
  if (missingRequiredPreviewBindingIds.value.length > 0) {
    messages.push(`Preview run 需要填写：${missingRequiredPreviewBindingIds.value.join(', ')}`)
  }
  for (const group of missingAlternativePreviewBindingGroups.value) {
    messages.push(`至少填写一个图片入口：${group.join(' 或 ')}`)
  }
  return messages
})
const previewHelpText = computed(() => {
  const messages = [...previewBlockingMessages.value]
  if (previewAlternativeImageBindingIds.value.length > 1) {
    messages.push(`图片入口至少填写一个：${previewAlternativeImageBindingIds.value.join(' 或 ')}`)
  }
  return messages.join('；')
})

function groupDefinitionsByCategory(definitions: NodeDefinition[]): PaletteGroup[] {
  const groupsByCategory = new Map<string, NodeDefinition[]>()
  for (const definition of definitions) {
    const groupDefinitions = groupsByCategory.get(definition.category) ?? []
    groupDefinitions.push(definition)
    groupsByCategory.set(definition.category, groupDefinitions)
  }
  return [...groupsByCategory.entries()]
    .sort(([leftCategory], [rightCategory]) => leftCategory.localeCompare(rightCategory))
    .map(([category, nodes]) => ({
      category,
      displayName: category.replaceAll('.', ' / '),
      nodes: [...nodes].sort((leftNode, rightNode) => leftNode.display_name.localeCompare(rightNode.display_name)),
    }))
}

function buildAppBoundaryNodes(): AppBoundaryNodeView[] {
  if (!workflowApp.value || graphNodes.value.length === 0) return []
  const minNodeX = Math.min(...graphNodes.value.map((node) => node.x))
  const minNodeY = Math.min(...graphNodes.value.map((node) => node.y))
  const maxNodeX = Math.max(...graphNodes.value.map((node) => node.x + node.width))
  return [
    {
      id: 'app-entry-boundary',
      kind: 'entry',
      title: 'App Entry',
      description: `公开输入 ${appInputBindings.value.length}`,
      x: minNodeX - 320,
      y: minNodeY,
      width: 250,
      bindings: appInputBindings.value,
    },
    {
      id: 'app-result-boundary',
      kind: 'result',
      title: 'App Result',
      description: `公开输出 ${appOutputBindings.value.length}`,
      x: maxNodeX + 140,
      y: minNodeY,
      width: 250,
      bindings: appOutputBindings.value,
    },
  ]
}

function getBindingPayloadTypeId(binding: FlowApplicationBinding): string {
  const configPayloadType = binding.config.payload_type_id
  if (typeof configPayloadType === 'string' && configPayloadType.trim()) return configPayloadType.trim()
  const metadataPayloadType = binding.metadata.payload_type_id
  if (typeof metadataPayloadType === 'string' && metadataPayloadType.trim()) return metadataPayloadType.trim()
  const templatePort = binding.direction === 'input' ? templateInputById.value.get(binding.template_port_id) : templateOutputById.value.get(binding.template_port_id)
  return templatePort?.payload_type_id ?? ''
}

function hasPreviewBindingValue(binding: FlowApplicationBinding): boolean {
  const state = previewInputState.value[binding.binding_id]
  if (!state) return false
  const payloadTypeId = getBindingPayloadTypeId(binding)
  if (payloadTypeId === 'value.v1') {
    return state.valueFields.some((field) => field.key.trim() && field.value.trim())
  }
  if (payloadTypeId === 'image-base64.v1') return state.file !== null
  if (payloadTypeId === 'image-ref.v1') {
    if (state.imageRefTransportKind === 'storage') return Boolean(state.objectKey.trim())
    return Boolean(state.imageHandle.trim() && state.mediaType.trim())
  }
  return Boolean(state.plainValue.trim())
}

function createEmptyPreviewInputState(binding: FlowApplicationBinding): PreviewInputState {
  const payloadTypeId = getBindingPayloadTypeId(binding)
  const valueFields = readPreviewValueFields(binding)
  if (payloadTypeId === 'value.v1' && valueFields.length === 0) {
    valueFields.push({ id: createPreviewFieldId(), key: binding.binding_id.includes('deployment') ? 'deployment_instance_id' : '', value: '' })
  }
  return {
    valueFields,
    file: null,
    mediaType: '',
    imageRefTransportKind: 'storage',
    objectKey: '',
    imageHandle: '',
    plainValue: '',
  }
}

function readPreviewValueFields(binding: FlowApplicationBinding): PreviewValueField[] {
  const rawValue = binding.config.default_value ?? binding.config.example_value ?? binding.metadata.default_value ?? binding.metadata.example_value
  const valueObject = normalizePreviewValueObject(rawValue)
  return Object.entries(valueObject).map(([key, value]) => ({ id: createPreviewFieldId(), key, value: String(value ?? '') }))
}

function normalizePreviewValueObject(rawValue: unknown): Record<string, unknown> {
  if (!rawValue || typeof rawValue !== 'object' || Array.isArray(rawValue)) return {}
  const rawRecord = rawValue as Record<string, unknown>
  const nestedValue = rawRecord.value
  if (nestedValue && typeof nestedValue === 'object' && !Array.isArray(nestedValue)) return nestedValue as Record<string, unknown>
  return rawRecord
}

function createPreviewFieldId(): string {
  return `preview-field-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`
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
  const position = readNodePosition(node, index, fallbackByNodeId)
  return {
    node,
    definition,
    title: definition?.display_name || node.node_type_id,
    x: position.x,
    y: position.y,
    width: readNumber(node.ui_state.width, 250),
    inputs: definition?.input_ports.length ? definition.input_ports : inferPortsFromEdges(node, 'input'),
    outputs: definition?.output_ports.length ? definition.output_ports : inferPortsFromEdges(node, 'output'),
  }
}

function buildGraphNodeViews(nodes: WorkflowGraphNode[]): GraphNodeView[] {
  const fallbackByNodeId = buildFallbackPositions(nodes, graphEdges.value)
  return nodes.map((node, index) => buildGraphNodeView(node, index, fallbackByNodeId))
}

function nodePortRows(node: GraphNodeView): NodePortRowView[] {
  const rowCount = Math.max(node.inputs.length, node.outputs.length)
  return Array.from({ length: rowCount }, (_, index) => ({
    key: `${node.node.node_id}-port-row-${index}`,
    input: node.inputs[index] ?? null,
    output: node.outputs[index] ?? null,
  }))
}

function nodeParameterFieldsForNode(node: GraphNodeView | null): NodeParameterUiField[] {
  if (!node?.definition?.parameter_ui_schema) return []
  return node.definition.parameter_ui_schema.fields.filter((field) => !field.hidden)
}

function isStringParameter(field: NodeParameterUiField): boolean {
  const type = field.json_schema.type
  return type === 'string' || type === undefined
}

function isNumberParameter(field: NodeParameterUiField): boolean {
  const type = field.json_schema.type
  return type === 'number' || type === 'integer'
}

function isBooleanParameter(field: NodeParameterUiField): boolean {
  return field.json_schema.type === 'boolean'
}

function readNodeParameterValue(node: GraphNodeView, field: NodeParameterUiField): unknown {
  const value = node.node.parameters[field.parameter_name]
  return value ?? field.default_value ?? ''
}

function readNodeParameterTextValue(node: GraphNodeView, field: NodeParameterUiField): string {
  const value = readNodeParameterValue(node, field)
  if (typeof value === 'string') return value
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  return ''
}

function readNodeParameterBooleanValue(node: GraphNodeView, field: NodeParameterUiField): boolean {
  const value = readNodeParameterValue(node, field)
  return value === true || value === 'true'
}

function readNodeParameterEnumIndex(node: GraphNodeView, field: NodeParameterUiField): string {
  const value = readNodeParameterValue(node, field)
  const optionIndex = field.enum_options.findIndex((option) => areParameterValuesEqual(option.value, value))
  return optionIndex >= 0 ? String(optionIndex) : ''
}

function areParameterValuesEqual(leftValue: unknown, rightValue: unknown): boolean {
  if (Object.is(leftValue, rightValue)) return true
  return String(leftValue) === String(rightValue)
}

function updateNodeParameterFromTextEvent(node: GraphNodeView, field: NodeParameterUiField, event: Event): void {
  const target = event.target
  if (!(target instanceof HTMLInputElement)) return
  updateNodeParameter(node, field, target.value)
}

function updateNodeParameterFromNumberEvent(node: GraphNodeView, field: NodeParameterUiField, event: Event): void {
  const target = event.target
  if (!(target instanceof HTMLInputElement)) return
  const value = target.value.trim()
  updateNodeParameter(node, field, value ? Number(value) : '')
}

function updateNodeParameterFromCheckboxEvent(node: GraphNodeView, field: NodeParameterUiField, event: Event): void {
  const target = event.target
  if (!(target instanceof HTMLInputElement)) return
  updateNodeParameter(node, field, target.checked)
}

function updateNodeParameterFromEnumEvent(node: GraphNodeView, field: NodeParameterUiField, event: Event): void {
  const target = event.target
  if (!(target instanceof HTMLSelectElement)) return
  const optionIndex = Number(target.value)
  if (!Number.isInteger(optionIndex) || optionIndex < 0) {
    updateNodeParameter(node, field, '')
    return
  }
  updateNodeParameter(node, field, field.enum_options[optionIndex]?.value ?? '')
}

function updateNodeParameter(node: GraphNodeView, field: NodeParameterUiField, value: unknown): void {
  const nextParameters = { ...node.node.parameters }
  if (!field.required && (value === '' || value === null || value === undefined)) {
    delete nextParameters[field.parameter_name]
  } else {
    nextParameters[field.parameter_name] = value
  }
  node.node.parameters = nextParameters
  statusMessage.value = '已更新节点参数'
}

function nodeVisualHeight(node: GraphNodeView): number {
  const portRowCount = Math.max(node.inputs.length, node.outputs.length)
  const parameterFieldCount = nodeParameterFieldsForNode(node).length
  const widgetHeight = parameterFieldCount > 0 ? 12 + Math.min(parameterFieldCount, 4) * graphNodeWidgetRowHeight : 0
  const previewHeight = getPreviewNodeImage(node.node.node_id) ? graphNodePreviewHeight : 0
  return Math.max(116, graphNodeHeaderHeight + portRowCount * graphPortRowHeight + widgetHeight + previewHeight + 22)
}

function portY(node: GraphNodeView, portName: string, direction: 'input' | 'output'): number {
  const ports = direction === 'input' ? node.inputs : node.outputs
  const index = Math.max(ports.findIndex((port) => port.name === portName), 0)
  return node.y + graphNodeHeaderHeight + index * graphPortRowHeight + graphPortRowHeight / 2
}

function portX(node: GraphNodeView, direction: 'input' | 'output'): number {
  return direction === 'input' ? node.x + graphPortInsetX : node.x + node.width - graphPortInsetX
}

function isPortConnected(nodeId: string, portName: string, direction: 'input' | 'output'): boolean {
  return graphEdges.value.some((edge) => direction === 'input'
    ? edge.target_node_id === nodeId && edge.target_port === portName
    : edge.source_node_id === nodeId && edge.source_port === portName)
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

function buildGraphLinks(edges: WorkflowGraphEdge[]): GraphLinkView[] {
  return edges.flatMap((edge) => {
    const sourceNode = graphNodes.value.find((node) => node.node.node_id === edge.source_node_id)
    const targetNode = graphNodes.value.find((node) => node.node.node_id === edge.target_node_id)
    if (!sourceNode || !targetNode) {
      return []
    }
    return [{
      edgeId: edge.edge_id,
      edge,
      sourceX: portX(sourceNode, 'output'),
      sourceY: portY(sourceNode, edge.source_port, 'output'),
      targetX: portX(targetNode, 'input'),
      targetY: portY(targetNode, edge.target_port, 'input'),
    }]
  })
}

function buildDraftLink(draft: ConnectionDraftState): GraphLinkView {
  const sourceX = draft.anchorDirection === 'output' ? draft.anchorX : draft.pointerX
  const sourceY = draft.anchorDirection === 'output' ? draft.anchorY : draft.pointerY
  const targetX = draft.anchorDirection === 'input' ? draft.anchorX : draft.pointerX
  const targetY = draft.anchorDirection === 'input' ? draft.anchorY : draft.pointerY
  return {
    edgeId: 'draft',
    edge: {
      edge_id: 'draft',
      source_node_id: draft.anchorDirection === 'output' ? draft.anchorNodeId : '',
      source_port: draft.anchorDirection === 'output' ? draft.anchorPort : '',
      target_node_id: draft.anchorDirection === 'input' ? draft.anchorNodeId : '',
      target_port: draft.anchorDirection === 'input' ? draft.anchorPort : '',
      metadata: {},
    },
    sourceX,
    sourceY,
    targetX,
    targetY,
  }
}

function linkPath(link: GraphLinkView): string {
  const control = linkControlPoints(link)
  return `M ${link.sourceX} ${link.sourceY} C ${control.sourceControlX} ${control.sourceControlY}, ${control.targetControlX} ${control.targetControlY}, ${link.targetX} ${link.targetY}`
}

function linkControlPoints(link: GraphLinkView): { sourceControlX: number; sourceControlY: number; targetControlX: number; targetControlY: number } {
  const distanceX = link.targetX - link.sourceX
  const forwardDistance = Math.max(distanceX, 0)
  const controlOffset = forwardDistance > 0
    ? Math.min(140, Math.max(1, forwardDistance / 2), Math.max(10, forwardDistance * 0.45))
    : Math.min(120, Math.max(42, Math.abs(distanceX) * 0.32))
  return {
    sourceControlX: link.sourceX + controlOffset,
    sourceControlY: link.sourceY,
    targetControlX: link.targetX - controlOffset,
    targetControlY: link.targetY,
  }
}

function linkPointAt(link: GraphLinkView, progress: number): { x: number; y: number } {
  const control = linkControlPoints(link)
  const t = clampNumber(progress, 0, 1)
  const inverse = 1 - t
  return {
    x: inverse ** 3 * link.sourceX + 3 * inverse ** 2 * t * control.sourceControlX + 3 * inverse * t ** 2 * control.targetControlX + t ** 3 * link.targetX,
    y: inverse ** 3 * link.sourceY + 3 * inverse ** 2 * t * control.sourceControlY + 3 * inverse * t ** 2 * control.targetControlY + t ** 3 * link.targetY,
  }
}

function selectNode(nodeId: string): void {
  selectedNodeId.value = nodeId
  selectedEdgeId.value = null
  selectedBoundaryKind.value = null
  connectionDraft.value = null
  contextMenu.value = null
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

function selectApplicationBoundary(kind: 'entry' | 'result'): void {
  selectedBoundaryKind.value = kind
  selectedNodeId.value = null
  selectedEdgeId.value = null
  connectionDraft.value = null
  contextMenu.value = null
}

function startPaletteDrag(event: DragEvent, definition: NodeDefinition): void {
  pendingPaletteNodeTypeId.value = definition.node_type_id
  event.dataTransfer?.setData('application/x-amvision-node-type-id', definition.node_type_id)
  if (event.dataTransfer) {
    event.dataTransfer.effectAllowed = 'copy'
  }
}

function dropPaletteNode(event: DragEvent): void {
  const nodeTypeId = event.dataTransfer?.getData('application/x-amvision-node-type-id') || pendingPaletteNodeTypeId.value
  pendingPaletteNodeTypeId.value = null
  if (!nodeTypeId) return
  const definition = nodeDefinitionsById.value.get(nodeTypeId)
  if (!definition) return
  const position = screenToWorld(event.clientX, event.clientY)
  addPaletteNode(definition, position.x, position.y)
}

function addPaletteNode(definition: NodeDefinition, rawX: number, rawY: number): void {
  const nodeId = createGraphNodeId(definition.node_type_id)
  const x = Math.round(rawX - 115)
  const y = Math.round(rawY - 40)
  const node: WorkflowGraphNode = {
    node_id: nodeId,
    node_type_id: definition.node_type_id,
    parameters: {},
    ui_state: { x, y, width: 250 },
    metadata: {},
  }
  graphNodes.value.push(buildGraphNodeView(node, graphNodes.value.length, new Map([[nodeId, { x, y }]])))
  selectedNodeId.value = nodeId
  statusMessage.value = '已添加节点'
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

function startConnectionDraft(event: MouseEvent, node: GraphNodeView, port: NodePortDefinition, anchorDirection: PortDirection, replacingEdgeId: string | null = null): void {
  const pointer = screenToWorld(event.clientX, event.clientY)
  connectionDraft.value = {
    anchorDirection,
    anchorNodeId: node.node.node_id,
    anchorPort: port.name,
    anchorX: portX(node, anchorDirection),
    anchorY: portY(node, port.name, anchorDirection),
    pointerX: pointer.x,
    pointerY: pointer.y,
    startClientX: event.clientX,
    startClientY: event.clientY,
    hasMoved: false,
    replacingEdgeId,
  }
  selectedNodeId.value = node.node.node_id
  selectedEdgeId.value = null
  selectedBoundaryKind.value = null
  contextMenu.value = null
  errorMessage.value = null
  document.addEventListener('mousemove', movePortConnection)
  document.addEventListener('mouseup', stopPortConnection)
}

function startEdgeTargetReconnect(event: MouseEvent, edgeId: string): void {
  const link = graphLinks.value.find((item) => item.edgeId === edgeId)
  if (!link) return
  const sourceNode = graphNodes.value.find((node) => node.node.node_id === link.edge.source_node_id)
  const sourcePort = sourceNode?.outputs.find((port) => port.name === link.edge.source_port)
  if (!sourceNode || !sourcePort) return
  const pointer = screenToWorld(event.clientX, event.clientY)
  connectionDraft.value = {
    anchorDirection: 'output',
    anchorNodeId: sourceNode.node.node_id,
    anchorPort: sourcePort.name,
    anchorX: link.sourceX,
    anchorY: link.sourceY,
    pointerX: pointer.x,
    pointerY: pointer.y,
    startClientX: event.clientX,
    startClientY: event.clientY,
    hasMoved: false,
    replacingEdgeId: edgeId,
  }
  selectedNodeId.value = null
  selectedEdgeId.value = edgeId
  selectedBoundaryKind.value = null
  contextMenu.value = null
  errorMessage.value = null
  document.addEventListener('mousemove', movePortConnection)
  document.addEventListener('mouseup', stopPortConnection)
}

function movePortConnection(event: MouseEvent): void {
  if (!connectionDraft.value) return
  const pointer = screenToWorld(event.clientX, event.clientY)
  const movedDistance = Math.hypot(event.clientX - connectionDraft.value.startClientX, event.clientY - connectionDraft.value.startClientY)
  connectionDraft.value = {
    ...connectionDraft.value,
    pointerX: pointer.x,
    pointerY: pointer.y,
    hasMoved: connectionDraft.value.hasMoved || movedDistance > 4,
  }
}

function stopPortConnection(event?: MouseEvent): void {
  const draft = connectionDraft.value
  let didConnect = false
  if (draft && event) {
    const targetPort = resolvePortElement(event.clientX, event.clientY)
    if (targetPort) {
      didConnect = connectDraftToPort(draft, targetPort)
    } else if (draft.hasMoved) {
      errorMessage.value = draft.anchorDirection === 'output' ? '请连接到输入端口' : '请连接到输出端口'
    }
    if (draft.hasMoved || didConnect) {
      suppressNodeClickOnce()
    }
  }
  connectionDraft.value = null
  document.removeEventListener('mousemove', movePortConnection)
  document.removeEventListener('mouseup', stopPortConnection)
}

function resolvePortElement(clientX: number, clientY: number): PortReference | null {
  const element = document.elementFromPoint(clientX, clientY)
  const portElement = element instanceof Element ? element.closest<HTMLElement>('.workflow-graph-port') : null
  if (!portElement) return null
  const nodeId = portElement.dataset.nodeId
  const portName = portElement.dataset.portName
  const direction = portElement.dataset.portDirection
  if (!nodeId || !portName || (direction !== 'input' && direction !== 'output')) return null
  return { nodeId, portName, direction }
}

function connectDraftToPort(draft: ConnectionDraftState, targetPort: PortReference): boolean {
  if (draft.anchorDirection === 'output') {
    if (targetPort.direction !== 'input') {
      if (draft.hasMoved) errorMessage.value = '请连接到输入端口'
      return false
    }
    return connectOutputToInput({ nodeId: draft.anchorNodeId, portName: draft.anchorPort, direction: 'output' }, targetPort, draft.replacingEdgeId)
  }
  if (targetPort.direction !== 'output') {
    if (draft.hasMoved) errorMessage.value = '请连接到输出端口'
    return false
  }
  return connectOutputToInput(targetPort, { nodeId: draft.anchorNodeId, portName: draft.anchorPort, direction: 'input' }, draft.replacingEdgeId)
}

function connectOutputToInput(sourcePortRef: PortReference, targetPortRef: PortReference, replacingEdgeId?: string | null): boolean {
  if (sourcePortRef.nodeId === targetPortRef.nodeId) {
    errorMessage.value = '不能把节点输出连接到同一个节点的输入'
    return false
  }
  const sourceNode = graphNodes.value.find((node) => node.node.node_id === sourcePortRef.nodeId)
  const targetNode = graphNodes.value.find((node) => node.node.node_id === targetPortRef.nodeId)
  if (!sourceNode || !targetNode) return false
  const sourcePort = sourceNode.outputs.find((port) => port.name === sourcePortRef.portName)
  const inputPort = targetNode.inputs.find((port) => port.name === targetPortRef.portName)
  if (!sourcePort || !inputPort) return false
  if (!portsCanConnect(sourcePort, inputPort)) {
    errorMessage.value = `端口类型不匹配：${sourcePort.payload_type_id || 'unknown'} -> ${inputPort.payload_type_id || 'unknown'}`
    return false
  }
  const nextEdge: WorkflowGraphEdge = {
    edge_id: createGraphEdgeId(sourcePortRef.nodeId, sourcePortRef.portName, targetPortRef.nodeId, targetPortRef.portName),
    source_node_id: sourcePortRef.nodeId,
    source_port: sourcePortRef.portName,
    target_node_id: targetPortRef.nodeId,
    target_port: targetPortRef.portName,
    metadata: {},
  }
  graphEdges.value = [
    ...graphEdges.value.filter((edge) => {
      if (replacingEdgeId && edge.edge_id === replacingEdgeId) return false
      if (edge.edge_id === nextEdge.edge_id) return false
      if (!inputPort.multiple && edge.target_node_id === nextEdge.target_node_id && edge.target_port === nextEdge.target_port) return false
      return true
    }),
    nextEdge,
  ]
  selectedNodeId.value = null
  selectedEdgeId.value = nextEdge.edge_id
  selectedBoundaryKind.value = null
  statusMessage.value = '已更新连线'
  errorMessage.value = null
  return true
}

function findInputEdge(nodeId: string, portName: string): WorkflowGraphEdge | null {
  return [...graphEdges.value].reverse().find((edge) => edge.target_node_id === nodeId && edge.target_port === portName) ?? null
}

function findOutputEdge(nodeId: string, portName: string): WorkflowGraphEdge | null {
  return [...graphEdges.value].reverse().find((edge) => edge.source_node_id === nodeId && edge.source_port === portName) ?? null
}

function portsCanConnect(sourcePort: NodePortDefinition, targetPort: NodePortDefinition): boolean {
  if (!sourcePort.payload_type_id || !targetPort.payload_type_id) return true
  return sourcePort.payload_type_id === targetPort.payload_type_id
}

function createGraphEdgeId(sourceNodeId: string, sourcePort: string, targetNodeId: string, targetPort: string): string {
  return `${sourceNodeId}_${sourcePort}_to_${targetNodeId}_${targetPort}`.replace(/[^a-zA-Z0-9]+/g, '_').replace(/^_+|_+$/g, '').toLowerCase() || 'edge'
}

function startStagePan(event: MouseEvent): void {
  if (event.button !== 0 || shouldIgnoreStagePointer(event.target)) return
  contextMenu.value = null
  panState.value = {
    startClientX: event.clientX,
    startClientY: event.clientY,
    startX: viewportX.value,
    startY: viewportY.value,
  }
  document.addEventListener('mousemove', moveStagePan)
  document.addEventListener('mouseup', stopStagePan)
}

function moveStagePan(event: MouseEvent): void {
  const pan = panState.value
  if (!pan) return
  viewportX.value = pan.startX + event.clientX - pan.startClientX
  viewportY.value = pan.startY + event.clientY - pan.startClientY
}

function stopStagePan(): void {
  panState.value = null
  document.removeEventListener('mousemove', moveStagePan)
  document.removeEventListener('mouseup', stopStagePan)
}

function shouldIgnoreStagePointer(target: EventTarget | null): boolean {
  return target instanceof Element && Boolean(target.closest('.workflow-graph-node, .workflow-graph-boundary-node, .workflow-graph-floating-panel, .workflow-graph-palette-toggle, .workflow-graph-minimap, .workflow-graph-minimap-toggle, .workflow-graph-context-menu, .workflow-graph-link, .workflow-graph-link-hit-area, .workflow-graph-link-handle, .workflow-graph-port'))
}

function shouldIgnoreStageWheelTarget(target: EventTarget | null): boolean {
  return target instanceof Element && Boolean(target.closest('input, textarea, select, button, .workflow-graph-floating-panel, .workflow-graph-minimap, .workflow-graph-minimap-toggle, .workflow-graph-context-menu, .image-viewer'))
}

function deleteSelectedNode(): void {
  const nodeId = selectedNodeId.value ?? contextMenu.value?.nodeId
  if (!nodeId) return
  graphNodes.value = graphNodes.value.filter((node) => node.node.node_id !== nodeId)
  graphEdges.value = graphEdges.value.filter((edge) => edge.source_node_id !== nodeId && edge.target_node_id !== nodeId)
  selectedNodeId.value = graphNodes.value[0]?.node.node_id ?? null
  selectedEdgeId.value = null
  selectedBoundaryKind.value = null
  contextMenu.value = null
  statusMessage.value = '已删除节点'
}

function deleteSelectedEdge(): void {
  const edgeId = selectedEdgeId.value ?? contextMenu.value?.edgeId
  if (!edgeId) return
  graphEdges.value = graphEdges.value.filter((edge) => edge.edge_id !== edgeId)
  selectedEdgeId.value = null
  selectedBoundaryKind.value = null
  contextMenu.value = null
  statusMessage.value = '已删除连线'
}

function openNodeContextMenu(event: MouseEvent, node: GraphNodeView): void {
  selectedNodeId.value = node.node.node_id
  selectedEdgeId.value = null
  selectedBoundaryKind.value = null
  contextMenu.value = { x: event.clientX, y: event.clientY, nodeId: node.node.node_id, edgeId: null }
}

function openEdgeContextMenu(event: MouseEvent, link: GraphLinkView): void {
  selectedEdgeId.value = link.edgeId
  selectedNodeId.value = null
  selectedBoundaryKind.value = null
  contextMenu.value = { x: event.clientX, y: event.clientY, nodeId: null, edgeId: link.edgeId }
}

function openStageContextMenu(event: MouseEvent): void {
  if (shouldIgnoreStagePointer(event.target)) return
  contextMenu.value = { x: event.clientX, y: event.clientY, nodeId: null, edgeId: null }
}

function calculateWorldBounds(): { minX: number; minY: number; maxX: number; maxY: number; width: number; height: number } {
  if (graphNodes.value.length === 0) {
    const viewLeft = -viewportX.value / viewportScale.value
    const viewTop = -viewportY.value / viewportScale.value
    const viewWidth = stageSize.value.width / viewportScale.value
    const viewHeight = stageSize.value.height / viewportScale.value
    return { minX: viewLeft, minY: viewTop, maxX: viewLeft + viewWidth, maxY: viewTop + viewHeight, width: viewWidth, height: viewHeight }
  }
  const minX = Math.min(...graphNodes.value.map((node) => node.x)) - 160
  const minY = Math.min(...graphNodes.value.map((node) => node.y)) - 120
  const maxX = Math.max(...graphNodes.value.map((node) => node.x + node.width)) + 160
  const maxY = Math.max(...graphNodes.value.map((node) => node.y + nodeVisualHeight(node))) + 120
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

function parameterHelpText(field: NodeParameterUiField): string {
  const messages: string[] = []
  if (field.description) messages.push(field.description)
  if (field.required) messages.push('必填参数')
  if (field.readonly) messages.push('只读参数')
  return messages.join('；')
}

function previewBindingHelpText(binding: FlowApplicationBinding): string {
  const payloadTypeId = getBindingPayloadTypeId(binding) || 'unknown'
  const requiredText = binding.required ? '必填输入' : '可选输入'
  if (payloadTypeId === 'image-base64.v1') return `${requiredText}。选择图片文件后会自动转换为 image-base64 payload。`
  if (payloadTypeId === 'image-ref.v1') return `${requiredText}。可填写 ObjectStore object_key，或填写运行内存 image_handle。`
  if (payloadTypeId === 'value.v1') return `${requiredText}。按字段名和值提交 value payload。`
  return `${requiredText}。payload type: ${payloadTypeId}。`
}

function initializePreviewInputs(applicationBindings: FlowApplicationBinding[]): void {
  const nextInputState: Record<string, PreviewInputState> = {}
  for (const binding of applicationBindings) {
    if (binding.direction !== 'input') continue
    nextInputState[binding.binding_id] = createEmptyPreviewInputState(binding)
  }
  previewInputState.value = nextInputState
}

function addPreviewValueField(bindingId: string): void {
  const state = previewInputState.value[bindingId]
  if (!state) return
  state.valueFields.push({ id: createPreviewFieldId(), key: '', value: '' })
}

function removePreviewValueField(bindingId: string, fieldId: string): void {
  const state = previewInputState.value[bindingId]
  if (!state) return
  state.valueFields = state.valueFields.filter((field) => field.id !== fieldId)
  if (state.valueFields.length === 0) addPreviewValueField(bindingId)
}

async function buildPreviewInputBindings(): Promise<Record<string, unknown> | null> {
  if (previewBlockingMessages.value.length > 0) {
    errorMessage.value = previewBlockingMessages.value.join('；')
    return null
  }
  const inputBindings: Record<string, unknown> = {}
  for (const binding of previewInputBindings.value) {
    if (!hasPreviewBindingValue(binding)) continue
    inputBindings[binding.binding_id] = await buildPreviewPayload(binding)
  }
  return inputBindings
}

async function buildPreviewPayload(binding: FlowApplicationBinding): Promise<unknown> {
  const state = previewInputState.value[binding.binding_id]
  const payloadTypeId = getBindingPayloadTypeId(binding)
  if (!state) return null
  if (payloadTypeId === 'value.v1') return buildValuePreviewPayload(state)
  if (payloadTypeId === 'image-base64.v1') return buildImageBase64PreviewPayload(state)
  if (payloadTypeId === 'image-ref.v1') return buildImageRefPreviewPayload(state)
  return { value: parsePreviewScalarValue(state.plainValue) }
}

function buildValuePreviewPayload(state: PreviewInputState): Record<string, unknown> {
  const value: Record<string, unknown> = {}
  for (const field of state.valueFields) {
    const key = field.key.trim()
    if (!key) continue
    value[key] = parsePreviewScalarValue(field.value)
  }
  return { value }
}

async function buildImageBase64PreviewPayload(state: PreviewInputState): Promise<Record<string, unknown>> {
  if (!state.file) return {}
  const imageBase64 = await readFileAsBase64(state.file)
  return {
    image_base64: imageBase64,
    media_type: state.mediaType.trim() || state.file.type || 'application/octet-stream',
  }
}

function buildImageRefPreviewPayload(state: PreviewInputState): Record<string, unknown> {
  if (state.imageRefTransportKind === 'memory') {
    return {
      transport_kind: 'memory',
      image_handle: state.imageHandle.trim(),
      media_type: state.mediaType.trim(),
    }
  }
  const payload: Record<string, unknown> = {
    transport_kind: 'storage',
    object_key: state.objectKey.trim(),
  }
  if (state.mediaType.trim()) payload.media_type = state.mediaType.trim()
  return payload
}

function parsePreviewScalarValue(value: string): unknown {
  const trimmedValue = value.trim()
  if (trimmedValue === 'true') return true
  if (trimmedValue === 'false') return false
  if (trimmedValue === 'null') return null
  if (trimmedValue !== '' && !Number.isNaN(Number(trimmedValue))) return Number(trimmedValue)
  return value
}

function readFileAsBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => {
      const result = typeof reader.result === 'string' ? reader.result : ''
      const commaIndex = result.indexOf(',')
      resolve(commaIndex >= 0 ? result.slice(commaIndex + 1) : result)
    }
    reader.onerror = () => reject(reader.error ?? new Error('读取图片文件失败'))
    reader.readAsDataURL(file)
  })
}

async function refreshPreviewNodeImages(previewRun: WorkflowPreviewRun): Promise<void> {
  revokePreviewImageObjectUrls()
  const nextImages: Record<string, PreviewNodeImageView> = {}
  for (const displayOutput of readPreviewDisplayOutputs(previewRun)) {
    const imageView = await buildPreviewNodeImageView(previewRun, displayOutput)
    if (imageView) {
      nextImages[imageView.nodeId] = imageView
    }
  }
  previewNodeImages.value = nextImages
}

function readPreviewDisplayOutputs(previewRun: WorkflowPreviewRun): WorkflowPreviewDisplayOutput[] {
  if (previewRun.preview_display_outputs?.length) return previewRun.preview_display_outputs
  return previewRun.node_records.flatMap((record) => {
    if (readDisplayText(record.node_type_id) !== 'core.io.image-preview') return []
    const outputs = record.outputs
    if (!isWorkflowJsonObject(outputs) || !isWorkflowJsonObject(outputs.body)) return []
    return [{
      node_id: readDisplayText(record.node_id),
      node_type_id: 'core.io.image-preview',
      output_name: 'body',
      payload: outputs.body,
    }]
  }).filter((displayOutput) => displayOutput.node_id)
}

async function buildPreviewNodeImageView(previewRun: WorkflowPreviewRun, displayOutput: WorkflowPreviewDisplayOutput): Promise<PreviewNodeImageView | null> {
  if (displayOutput.node_type_id !== 'core.io.image-preview') return null
  const payload = displayOutput.payload
  if (payload.type !== 'image-preview' || !isWorkflowJsonObject(payload.image)) return null
  const imagePayload = payload.image
  const title = readDisplayText(payload.title) || displayOutput.node_id
  const transportKind = readDisplayText(imagePayload.transport_kind) || 'unknown'
  const mediaType = readDisplayText(imagePayload.media_type)
  const objectKey = readDisplayText(imagePayload.object_key) || null
  const imageBase64 = readDisplayText(imagePayload.image_base64)
  const src = imageBase64 ? `data:${mediaType || 'image/png'};base64,${imageBase64}` : await resolveStoragePreviewImageSrc(previewRun, objectKey)
  return {
    nodeId: displayOutput.node_id,
    title,
    src,
    statusText: src ? '预览图已生成' : buildPreviewImageStatusText(transportKind, objectKey),
    transportKind,
    mediaType,
    width: readDisplayNumber(imagePayload.width),
    height: readDisplayNumber(imagePayload.height),
    objectKey,
  }
}

async function resolveStoragePreviewImageSrc(previewRun: WorkflowPreviewRun, objectKey: string | null): Promise<string | null> {
  if (!objectKey) return null
  try {
    const blob = await readPreviewImageBlob(previewRun, objectKey)
    if (!blob) return null
    const objectUrl = URL.createObjectURL(blob)
    previewImageObjectUrls.push(objectUrl)
    return objectUrl
  } catch (error) {
    console.warn('读取 Preview 图片失败', error)
    return null
  }
}

async function readPreviewImageBlob(previewRun: WorkflowPreviewRun, objectKey: string): Promise<Blob | null> {
  if (objectKey.startsWith(`workflows/runtime/preview-runs/${previewRun.preview_run_id}/artifacts/`)) {
    return readWorkflowPreviewRunArtifactBlob(previewRun.preview_run_id, objectKey)
  }
  if (objectKey.startsWith(`projects/${previewRun.project_id}/`)) {
    return readProjectObjectContentBlob(previewRun.project_id, objectKey)
  }
  return null
}

function buildPreviewImageStatusText(transportKind: string, objectKey: string | null): string {
  if (transportKind === 'storage-ref' && objectKey) return '预览图引用暂不可读取'
  return '本次 Preview 未返回可展示图片'
}

function revokePreviewImageObjectUrls(): void {
  for (const objectUrl of previewImageObjectUrls) {
    URL.revokeObjectURL(objectUrl)
  }
  previewImageObjectUrls = []
  previewNodeImages.value = {}
  activeImageViewer.value = null
}

function getPreviewNodeImage(nodeId: string): PreviewNodeImageView | null {
  return previewNodeImages.value[nodeId] ?? null
}

function openImageViewer(image: PreviewNodeImageView | null): void {
  if (!image?.src) return
  activeImageViewer.value = image
}

function isWorkflowJsonObject(value: unknown): value is WorkflowJsonObject {
  return Boolean(value && typeof value === 'object' && !Array.isArray(value))
}

function readDisplayText(value: unknown): string {
  return typeof value === 'string' && value.trim() ? value.trim() : ''
}

function readDisplayNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
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
  }
}

function buildCurrentTemplate() {
  const sourceTemplate = workflowApp.value?.graphDocument.template
  if (!sourceTemplate) return null
  const snapshot = createCanvasSnapshot()
  return liteGraphAdapter.value?.exportTemplate(sourceTemplate, snapshot) ?? sourceTemplate
}

async function saveCurrentWorkflowApp(): Promise<void> {
  if (!workflowApp.value) return
  const template = buildCurrentTemplate()
  if (!template) return
  saving.value = true
  errorMessage.value = null
  statusMessage.value = null
  contextMenu.value = null
  try {
    const result = await saveWorkflowApp({
      projectId: selectedProjectId.value,
      application: workflowApp.value.applicationDocument.application,
      template,
    })
    workflowApp.value = {
      ...workflowApp.value,
      applicationDocument: result.applicationDocument,
      graphDocument: result.graphDocument,
    }
    statusMessage.value = '已保存'
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '保存失败'
  } finally {
    saving.value = false
  }
}

async function runPreview(): Promise<void> {
  if (!workflowApp.value) return
  const template = buildCurrentTemplate()
  if (!template) return
  const inputBindings = await buildPreviewInputBindings()
  if (!inputBindings) return
  previewing.value = true
  errorMessage.value = null
  statusMessage.value = null
  contextMenu.value = null
  revokePreviewImageObjectUrls()
  try {
    lastPreviewRun.value = await createWorkflowPreviewRun({
      projectId: selectedProjectId.value,
      application: workflowApp.value.applicationDocument.application,
      template,
      inputBindings,
      executionMetadata: { source: 'workflow-graph-workbench' },
      waitMode: 'sync',
    })
    await refreshPreviewNodeImages(lastPreviewRun.value)
    if (lastPreviewRun.value.state === 'failed') {
      errorMessage.value = lastPreviewRun.value.error_message || 'Preview run failed'
    }
    statusMessage.value = `Preview ${lastPreviewRun.value.state}`
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : 'Preview run 失败'
  } finally {
    previewing.value = false
  }
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
  errorMessage.value = null
  statusMessage.value = null
  lastPreviewRun.value = null
  revokePreviewImageObjectUrls()
  try {
    nodeCatalog.value = await getWorkflowNodeCatalog()
    liteGraphAdapter.value = createWorkflowLiteGraphAdapter({ nodeDefinitions: nodeCatalog.value.node_definitions })
    if (!isNewApp.value && routeApplicationId.value) {
      workflowApp.value = await getWorkflowApp(selectedProjectId.value, routeApplicationId.value)
      initializePreviewInputs(workflowApp.value.applicationDocument.application.bindings)
      liteGraphAdapter.value.loadTemplate(workflowApp.value.graphDocument.template)
      graphEdges.value = workflowApp.value.graphDocument.template.edges.map((edge) => ({ ...edge, metadata: { ...edge.metadata } }))
      graphNodes.value = buildGraphNodeViews(workflowApp.value.graphDocument.template.nodes)
      selectedNodeId.value = graphNodes.value[0]?.node.node_id ?? null
      selectedEdgeId.value = null
      selectedBoundaryKind.value = null
    } else {
      workflowApp.value = null
      graphEdges.value = []
      graphNodes.value = []
      selectedNodeId.value = null
      selectedEdgeId.value = null
      selectedBoundaryKind.value = null
      previewInputState.value = {}
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
  stopPortConnection()
  stopStagePan()
  stopMinimapNavigation()
  revokePreviewImageObjectUrls()
  window.removeEventListener('keydown', handleKeydown)
  window.removeEventListener('resize', updateStageSize)
  resizeObserver?.disconnect()
})
</script>
