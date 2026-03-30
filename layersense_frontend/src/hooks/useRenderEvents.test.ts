import { renderHook } from '@testing-library/react'
import { describe, expect, it, vi, beforeEach } from 'vitest'

import { useRenderEvents } from './useRenderEvents'

class MockWebSocket {
  static instances: MockWebSocket[] = []

  readonly url: string
  closeCalls = 0
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

  listenerCount(event: string): number {
    return this.listeners.get(event)?.size ?? 0
  }

  close(): void {
    this.closeCalls += 1
  }

  emitClose(): void {
    const listeners = this.listeners.get('close')
    if (!listeners) {
      return
    }

    const event = {} as CloseEvent
    listeners.forEach((listener) => listener(event as unknown as Event))
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
    vi.useRealTimers()
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

  it('keeps the same websocket instance when conversationId changes', () => {
    const { rerender } = renderHook(
      ({ conversationId }) => useRenderEvents({ conversationId }),
      { initialProps: { conversationId: 'conv-1' } },
    )

    const initialSocket = MockWebSocket.instances[0]
    rerender({ conversationId: 'conv-2' })

    expect(MockWebSocket.instances).toHaveLength(1)
    expect(MockWebSocket.instances[0]).toBe(initialSocket)
  })

  it('reconnects after a short delay when the socket closes unexpectedly', () => {
    vi.useFakeTimers()

    renderHook(() => useRenderEvents({ conversationId: 'conv-1' }))

    const initialSocket = MockWebSocket.instances[0]
    initialSocket.emitClose()

    expect(MockWebSocket.instances).toHaveLength(1)

    vi.advanceTimersByTime(999)
    expect(MockWebSocket.instances).toHaveLength(1)

    vi.advanceTimersByTime(1)
    expect(MockWebSocket.instances).toHaveLength(2)
    expect(MockWebSocket.instances[1]).not.toBe(initialSocket)
    expect(MockWebSocket.instances[1]?.url).toBe('ws://localhost:8001/ws')
  })

  it('removes listeners from a closed socket and cancels reconnect on unmount', () => {
    vi.useFakeTimers()

    const { unmount } = renderHook(() => useRenderEvents({ conversationId: 'conv-1' }))

    const initialSocket = MockWebSocket.instances[0]
    expect(initialSocket.listenerCount('message')).toBe(1)
    expect(initialSocket.listenerCount('close')).toBe(1)

    initialSocket.emitClose()

    expect(initialSocket.listenerCount('message')).toBe(0)
    expect(initialSocket.listenerCount('close')).toBe(0)

    unmount()
    vi.runAllTimers()

    expect(MockWebSocket.instances).toHaveLength(1)
  })

  it('closes the active socket on unmount', () => {
    const { unmount } = renderHook(() => useRenderEvents({ conversationId: 'conv-1' }))

    const socket = MockWebSocket.instances[0]
    unmount()

    expect(socket.closeCalls).toBe(1)
  })

  it('ignores payloads missing required event-specific fields', () => {
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
    socket.emitMessage({ type: 'artifact_ready', conversation_id: 'conv-1', preview_url: '/preview.mp4' })
    socket.emitMessage({ type: 'preview_ready', conversation_id: 'conv-1' })
    socket.emitMessage({ type: 'render_ready', conversation_id: 'conv-1' })
    socket.emitMessage({ type: 'render_failed', conversation_id: 'conv-1' })

    expect(onArtifactReady).not.toHaveBeenCalled()
    expect(onPreviewReady).not.toHaveBeenCalled()
    expect(onRenderReady).not.toHaveBeenCalled()
    expect(onRenderFailed).not.toHaveBeenCalled()
  })
})
