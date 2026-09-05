import type { FlowApplicationBinding } from '../types'

type Translate = (key: string) => string

const standardInputLabelKeys: Record<string, string> = {
  request_image_ref: 'workflowEditor.appMode.inputImage',
  request_image_base64: 'workflowEditor.appMode.inputImageBase64',
  request_json: 'workflowEditor.appMode.inputJson',
  request_text: 'workflowEditor.appMode.inputText',
  request_file: 'workflowEditor.appMode.inputFile',
  request_files: 'workflowEditor.appMode.inputFiles',
}

export function readWorkflowInputLabel(
  bindingId: string,
  configuredLabel: unknown,
  translate: Translate,
): string {
  const standardLabelKey = standardInputLabelKeys[bindingId]
  if (standardLabelKey) return translate(standardLabelKey)
  if (typeof configuredLabel === 'string' && configuredLabel.trim() && configuredLabel.trim() !== bindingId) {
    return configuredLabel.trim()
  }
  return bindingId
    .replace(/[_-]+/g, ' ')
    .replace(/\b\w/g, (character) => character.toUpperCase())
    .trim()
}

export function readWorkflowInputBindingLabel(
  binding: FlowApplicationBinding,
  translate: Translate,
): string {
  return readWorkflowInputLabel(binding.binding_id, binding.metadata.display_name, translate)
}
