import type { ExcalidrawElement } from '@excalidraw/excalidraw/element/types'
import type { AppState, BinaryFiles } from '@excalidraw/excalidraw/types'

export type ExcalidrawSceneSnapshot = {
  elements: readonly ExcalidrawElement[]
  appState: Partial<AppState>
  files: BinaryFiles
}

export type AnimationRequest = {
  prompt: string
  scene: ExcalidrawSceneSnapshot
  conversation_id?: string
}

export type AnimationResponse = {
  conversation_id: string
  scene_path: string
}

export type RenderQueueRequest = {
  scene_path: string
  conversation_id: string
}

export type RenderQueueResponse = {
  status: 'cached' | 'queued'
}

export type ArtifactReadyEvent = {
  type: 'artifact_ready'
  conversation_id: string
  preview_url: string
  final_url: string
}

export type PreviewReadyEvent = {
  type: 'preview_ready'
  conversation_id: string
  url: string
}

export type RenderReadyEvent = {
  type: 'render_ready'
  conversation_id: string
  url: string
}

export type RenderFailedEvent = {
  type: 'render_failed'
  conversation_id: string
  error: string
  stderr?: string
}

export type RenderEvent = ArtifactReadyEvent | PreviewReadyEvent | RenderReadyEvent | RenderFailedEvent
