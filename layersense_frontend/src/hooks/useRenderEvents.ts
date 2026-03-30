import { useEffect, useRef } from 'react'

import type { RenderEvent } from '../types'

const WS_URL = 'ws://localhost:8001/ws'
const RECONNECT_DELAY_MS = 1000

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
  if (typeof event.type !== 'string' || typeof event.conversation_id !== 'string') {
    return false
  }

  switch (event.type) {
    case 'artifact_ready':
      return typeof event.preview_url === 'string' && typeof event.final_url === 'string'
    case 'preview_ready':
    case 'render_ready':
      return typeof event.url === 'string'
    case 'render_failed':
      return typeof event.error === 'string' && (event.stderr === undefined || typeof event.stderr === 'string')
    default:
      return false
  }
}

export const useRenderEvents = ({
  conversationId,
  onArtifactReady,
  onPreviewReady,
  onRenderReady,
  onRenderFailed,
}: UseRenderEventsParams): void => {
  const latestConversationIdRef = useRef(conversationId)
  const latestHandlersRef = useRef({
    onArtifactReady,
    onPreviewReady,
    onRenderReady,
    onRenderFailed,
  })

  useEffect(() => {
    latestConversationIdRef.current = conversationId
    latestHandlersRef.current = {
      onArtifactReady,
      onPreviewReady,
      onRenderReady,
      onRenderFailed,
    }
  }, [conversationId, onArtifactReady, onPreviewReady, onRenderReady, onRenderFailed])

  useEffect(() => {
    let isUnmounted = false
    let socket: WebSocket | null = null
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null

    const cleanupSocket = (): void => {
      if (!socket) {
        return
      }

      socket.removeEventListener('message', onMessage as EventListener)
      socket.removeEventListener('close', onClose as EventListener)
      socket = null
    }

    const scheduleReconnect = (): void => {
      if (isUnmounted || reconnectTimer) {
        return
      }

      reconnectTimer = setTimeout(() => {
        reconnectTimer = null
        connect()
      }, RECONNECT_DELAY_MS)
    }

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

      if (!latestConversationIdRef.current || payload.conversation_id !== latestConversationIdRef.current) {
        return
      }

      const handlers = latestHandlersRef.current

      switch (payload.type) {
        case 'artifact_ready':
          handlers.onArtifactReady?.({ previewUrl: payload.preview_url, finalUrl: payload.final_url })
          return
        case 'preview_ready':
          handlers.onPreviewReady?.(payload.url)
          return
        case 'render_ready':
          handlers.onRenderReady?.(payload.url)
          return
        case 'render_failed':
          handlers.onRenderFailed?.({ error: payload.error, stderr: payload.stderr })
          return
      }
    }

    const onClose = (): void => {
      cleanupSocket()
      scheduleReconnect()
    }

    const connect = (): void => {
      socket = new WebSocket(WS_URL)

      socket.addEventListener('message', onMessage as EventListener)
      socket.addEventListener('close', onClose as EventListener)
    }

    connect()

    return () => {
      isUnmounted = true
      if (reconnectTimer) {
        clearTimeout(reconnectTimer)
        reconnectTimer = null
      }
      const activeSocket = socket
      cleanupSocket()
      activeSocket?.close()
    }
  }, [])
}
