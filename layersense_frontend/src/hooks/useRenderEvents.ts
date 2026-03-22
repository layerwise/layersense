import { useEffect } from 'react'

import type { RenderEvent } from '../types'

const WS_URL = 'ws://localhost:8001/ws'

type UseRenderEventsParams = {
  conversationId: string | null
  onArtifactReady?: (payload: { previewUrl: string; finalUrl: string }) => void
  onPreviewReady?: (url: string) => void
  onRenderReady?: (url: string) => void
  onRenderFailed?: (payload: { error: string; stderr?: string }) => void
}

const isRenderEvent = (value: unknown): value is RenderEvent => {
  if (!value || typeof value !== 'object') {
    return false
  }

  const event = value as Record<string, unknown>
  return typeof event.type === 'string' && typeof event.conversation_id === 'string'
}

export const useRenderEvents = ({
  conversationId,
  onArtifactReady,
  onPreviewReady,
  onRenderReady,
  onRenderFailed,
}: UseRenderEventsParams): void => {
  useEffect(() => {
    const socket = new WebSocket(WS_URL)

    const onMessage = (message: MessageEvent<string>): void => {
      let payload: unknown
      try {
        payload = JSON.parse(message.data)
      } catch {
        return
      }

      if (!isRenderEvent(payload)) {
        return
      }

      if (!conversationId || payload.conversation_id !== conversationId) {
        return
      }

      switch (payload.type) {
        case 'artifact_ready':
          onArtifactReady?.({ previewUrl: payload.preview_url, finalUrl: payload.final_url })
          return
        case 'preview_ready':
          onPreviewReady?.(payload.url)
          return
        case 'render_ready':
          onRenderReady?.(payload.url)
          return
        case 'render_failed':
          onRenderFailed?.({ error: payload.error, stderr: payload.stderr })
          return
      }
    }

    socket.addEventListener('message', onMessage as EventListener)

    return () => {
      socket.removeEventListener('message', onMessage as EventListener)
      socket.close()
    }
  }, [conversationId, onArtifactReady, onPreviewReady, onRenderReady, onRenderFailed])
}
