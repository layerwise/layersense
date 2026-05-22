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
  source_code: string
  content_hash: string
}

export type CLIFlags = {
  quality?: 'l' | 'm' | 'h' | 'p' | 'k'
  resolution?: string
  frame_rate?: number
  renderer?: 'cairo' | 'opengl'
  from_animation_number?: string
}

export type RenderQueueRequest = {
  source_code: string
  content_hash: string
  conversation_id: string
  cli_flags?: CLIFlags
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
