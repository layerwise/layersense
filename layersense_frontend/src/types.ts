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
  render_options: RenderOptions
}

export type RenderOptions = {
  background_color: string | null
}

export type RenderQueueRequest = {
  scene_path: string
  conversation_id: string
  render_options: RenderOptions
}

export type RenderJobStatus =
  | 'queued'
  | 'preview_rendering'
  | 'waiting_for_final'
  | 'final_rendering'
  | 'succeeded'
  | 'failed'

export type RenderJobSnapshot = {
  job_id: string
  conversation_id: string
  status: RenderJobStatus
  version: number
  preview_url: string | null
  final_url: string | null
  error: string | null
  stderr: string | null
}

export type RenderQueueResponse = {
  job_id: string
  job: RenderJobSnapshot
}
