export interface ImageViewerPreviewHandlers<TEvent> {
  previewInteraction: (event: TEvent) => void
  runPreview: () => void
}

export function dispatchImageViewerPreview<TEvent>(
  hasInteractionDraft: boolean,
  interactionEvent: TEvent | null,
  handlers: ImageViewerPreviewHandlers<TEvent>,
): 'interaction' | 'preview' | 'invalid' {
  if (hasInteractionDraft) {
    if (interactionEvent === null) return 'invalid'
    handlers.previewInteraction(interactionEvent)
    return 'interaction'
  }
  handlers.runPreview()
  return 'preview'
}
