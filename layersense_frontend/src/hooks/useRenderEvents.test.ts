import { renderHook } from '@testing-library/react'
import { describe, expect, it, vi, beforeEach } from 'vitest'

import { useRenderEvents } from './useRenderEvents'

class MockWebSocket {
  static instances: MockWebSocket[] = []

  readonly url: string
  private listeners = new Map<string, Set<EventListener>>()

  constructor(url: string) {
    this.url = url
    MockWebSocket.instances.push(this)
  }

  addEventListener(event: string, listener: EventListener): void {
    const listeners = this.listeners.get(event) ?? new Set<EventListener>()
    listeners.add(listener)
    this.listeners.set(event, listeners)
  }

  removeEventListener(event: string, listener: EventListener): void {
    const listeners = this.listeners.get(event)
    if (!listeners) {
      return
    }
    listeners.delete(listener)
  }

  close(): void {
    // no-op
  }

  emitMessage(data: unknown): void {
    const listeners = this.listeners.get('message')
    if (!listeners) {
      return
    }

    const event = { data: JSON.stringify(data) } as MessageEvent<string>
    listeners.forEach((listener) => listener(event as unknown as Event))
  }

  emitRaw(data: string): void {
    const listeners = this.listeners.get('message')
    if (!listeners) {
      return
    }

    const event = { data } as MessageEvent<string>
    listeners.forEach((listener) => listener(event as unknown as Event))
  }
}

describe('useRenderEvents', () => {
  beforeEach(() => {
    MockWebSocket.instances = []
    vi.stubGlobal('WebSocket', MockWebSocket as unknown as typeof WebSocket)
  })

  it('connects to controller websocket endpoint', () => {
    renderHook(() => useRenderEvents({ conversationId: null }))
    expect(MockWebSocket.instances[0]?.url).toBe('ws://localhost:8001/ws')
  })

  it('ignores events for other conversations', () => {
    const onPreviewReady = vi.fn()

    renderHook(() => useRenderEvents({ conversationId: 'conv-1', onPreviewReady }))
    const socket = MockWebSocket.instances[0]
    socket.emitMessage({ type: 'preview_ready', conversation_id: 'conv-2', url: '/preview.mp4' })

    expect(onPreviewReady).not.toHaveBeenCalled()
  })

  it('routes supported events to callbacks', () => {
    const onArtifactReady = vi.fn()
    const onPreviewReady = vi.fn()
    const onRenderReady = vi.fn()
    const onRenderFailed = vi.fn()

    renderHook(() =>
      useRenderEvents({
        conversationId: 'conv-1',
        onArtifactReady,
        onPreviewReady,
        onRenderReady,
        onRenderFailed,
      }),
    )

    const socket = MockWebSocket.instances[0]
    socket.emitMessage({
      type: 'artifact_ready',
      conversation_id: 'conv-1',
      preview_url: '/preview.mp4',
      final_url: '/final.mp4',
    })
    socket.emitMessage({ type: 'preview_ready', conversation_id: 'conv-1', url: '/preview2.mp4' })
    socket.emitMessage({ type: 'render_ready', conversation_id: 'conv-1', url: '/final2.mp4' })
    socket.emitMessage({ type: 'render_failed', conversation_id: 'conv-1', error: 'boom' })

    expect(onArtifactReady).toHaveBeenCalledWith({ previewUrl: '/preview.mp4', finalUrl: '/final.mp4' })
    expect(onPreviewReady).toHaveBeenCalledWith('/preview2.mp4')
    expect(onRenderReady).toHaveBeenCalledWith('/final2.mp4')
    expect(onRenderFailed).toHaveBeenCalledWith({ error: 'boom', stderr: undefined })
  })

  it('ignores invalid JSON payloads', () => {
    const onPreviewReady = vi.fn()

    renderHook(() => useRenderEvents({ conversationId: 'conv-1', onPreviewReady }))
    const socket = MockWebSocket.instances[0]
    socket.emitRaw('{bad json')

    expect(onPreviewReady).not.toHaveBeenCalled()
  })
})
