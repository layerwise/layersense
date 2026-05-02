import { act, cleanup, fireEvent, render, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { CONTROLLER_BASE } from './api'
import App from './App'

const mockCreateAnimation = vi.fn()
const mockQueueRender = vi.fn()
const hookState = {
  conversationId: null as string | null,
  handlers: {
    onArtifactReady: undefined as undefined | ((payload: { previewUrl: string; finalUrl: string }) => void),
    onPreviewReady: undefined as undefined | ((url: string) => void),
    onRenderReady: undefined as undefined | ((url: string) => void),
    onRenderFailed: undefined as undefined | ((payload: { error: string; stderr?: string }) => void),
  },
}

vi.mock('./api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./api')>()

  return {
    ...actual,
    createAnimation: (...args: unknown[]) => mockCreateAnimation(...args),
    queueRender: (...args: unknown[]) => mockQueueRender(...args),
  }
})

vi.mock('./components/Canvas', () => ({
  Canvas: ({ ref }: { ref: React.Ref<{ getSceneSnapshot: () => unknown }> }) => {
    if (ref && typeof ref === 'object') {
      ref.current = {
        getSceneSnapshot: () => ({
          elements: [{ id: 'elem-1' }],
          appState: { viewBackgroundColor: '#fff' },
          files: { fileA: { id: 'fileA' } },
        }),
      }
    }

    return <div data-testid="mock-canvas" />
  },
}))

vi.mock('./hooks/useRenderEvents', () => ({
  useRenderEvents: (params: {
    conversationId: string | null
    onArtifactReady?: (payload: { previewUrl: string; finalUrl: string }) => void
    onPreviewReady?: (url: string) => void
    onRenderReady?: (url: string) => void
    onRenderFailed?: (payload: { error: string; stderr?: string }) => void
  }) => {
    hookState.conversationId = params.conversationId
    hookState.handlers = {
      onArtifactReady: params.onArtifactReady,
      onPreviewReady: params.onPreviewReady,
      onRenderReady: params.onRenderReady,
      onRenderFailed: params.onRenderFailed,
    }
  },
}))

describe('App', () => {
  afterEach(() => {
    cleanup()
  })

  beforeEach(() => {
    mockCreateAnimation.mockReset()
    mockQueueRender.mockReset()
    hookState.conversationId = null
    hookState.handlers = {
      onArtifactReady: undefined,
      onPreviewReady: undefined,
      onRenderReady: undefined,
      onRenderFailed: undefined,
    }
  })

  it('disables Generate while submitting and queueing', async () => {
    let resolveCreate: (value: unknown) => void
    let resolveQueue: (value: unknown) => void

    mockCreateAnimation.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveCreate = resolve
        }),
    )
    mockQueueRender.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveQueue = resolve
        }),
    )

    const { getByRole } = render(<App />)
    const button = getByRole('button', { name: 'Generate' }) as HTMLButtonElement

    fireEvent.click(button)
    expect(button.disabled).toBe(true)

    resolveCreate!({
      conversation_id: 'conv-1',
      scene_path: '/tmp/scene.py',
      render_options: { background_color: '#fff' },
    })
    await waitFor(() => expect(mockQueueRender).toHaveBeenCalledTimes(1))
    expect(button.disabled).toBe(true)

    resolveQueue!({ status: 'queued' })
    await waitFor(() => expect(button.disabled).toBe(false))
  })

  it('sends prompt and scene snapshot to createAnimation', async () => {
    mockCreateAnimation.mockResolvedValue({
      conversation_id: 'conv-1',
      scene_path: '/tmp/scene.py',
      render_options: { background_color: '#fff' },
    })
    mockQueueRender.mockResolvedValue({ status: 'queued' })

    const { getByRole, getByLabelText } = render(<App />)
    const input = getByLabelText('Describe the animation sequence') as HTMLTextAreaElement
    fireEvent.change(input, { target: { value: 'animate a square' } })

    fireEvent.click(getByRole('button', { name: 'Generate' }))

    await waitFor(() => expect(mockCreateAnimation).toHaveBeenCalledTimes(1))
    expect(mockCreateAnimation).toHaveBeenCalledWith({
      prompt: 'animate a square',
      scene: {
        elements: [{ id: 'elem-1' }],
        appState: { viewBackgroundColor: '#fff' },
        files: { fileA: { id: 'fileA' } },
      },
    })
  })

  it('starts a new conversation on each Generate click', async () => {
    mockCreateAnimation
      .mockResolvedValueOnce({
        conversation_id: 'conv-1',
        scene_path: '/tmp/scene-1.py',
        render_options: { background_color: '#112233' },
      })
      .mockResolvedValueOnce({
        conversation_id: 'conv-2',
        scene_path: '/tmp/scene-2.py',
        render_options: { background_color: '#445566' },
      })
    mockQueueRender.mockResolvedValue({ status: 'queued' })

    const { getByRole } = render(<App />)
    const button = getByRole('button', { name: 'Generate' })

    fireEvent.click(button)
    await waitFor(() =>
      expect(mockQueueRender).toHaveBeenCalledWith({
        scene_path: '/tmp/scene-1.py',
        conversation_id: 'conv-1',
        render_options: { background_color: '#112233' },
      }),
    )

    fireEvent.click(button)
    await waitFor(() =>
      expect(mockQueueRender).toHaveBeenCalledWith({
        scene_path: '/tmp/scene-2.py',
        conversation_id: 'conv-2',
        render_options: { background_color: '#445566' },
      }),
    )
  })

  it('forwards null background render options unchanged', async () => {
    mockCreateAnimation.mockResolvedValue({
      conversation_id: 'conv-null-bg',
      scene_path: '/tmp/scene-null.py',
      render_options: { background_color: null },
    })
    mockQueueRender.mockResolvedValue({ status: 'queued' })

    const { getByRole } = render(<App />)
    fireEvent.click(getByRole('button', { name: 'Generate' }))

    await waitFor(() =>
      expect(mockQueueRender).toHaveBeenCalledWith({
        scene_path: '/tmp/scene-null.py',
        conversation_id: 'conv-null-bg',
        render_options: { background_color: null },
      }),
    )
  })

  it('updates media immediately on cached artifact_ready event', async () => {
    mockCreateAnimation.mockResolvedValue({
      conversation_id: 'conv-1',
      scene_path: '/tmp/scene.py',
      render_options: { background_color: '#fff' },
    })
    mockQueueRender.mockResolvedValue({ status: 'cached' })

    const { getByRole, getByTestId } = render(<App />)
    fireEvent.click(getByRole('button', { name: 'Generate' }))

    await waitFor(() => expect(hookState.conversationId).toBe('conv-1'))
    act(() => {
      hookState.handlers.onArtifactReady?.({ previewUrl: '/preview.mp4', finalUrl: '/final.mp4' })
    })

    await waitFor(() => {
      const video = getByTestId('render-video') as HTMLVideoElement
      expect(video.getAttribute('src')).toContain('/final.mp4')
    })
  })

  it('uses controller base URL for cached artifact video sources', async () => {
    mockCreateAnimation.mockResolvedValue({
      conversation_id: 'conv-1',
      scene_path: '/tmp/scene.py',
      render_options: { background_color: '#fff' },
    })
    mockQueueRender.mockResolvedValue({ status: 'cached' })

    const { getByRole, getByTestId } = render(<App />)
    fireEvent.click(getByRole('button', { name: 'Generate' }))

    await waitFor(() => expect(hookState.conversationId).toBe('conv-1'))
    act(() => {
      hookState.handlers.onArtifactReady?.({
        previewUrl: '/artifacts/preview.mp4',
        finalUrl: '/artifacts/final.mp4',
      })
    })

    await waitFor(() => {
      const video = getByTestId('render-video') as HTMLVideoElement
      expect(video.getAttribute('src')).toBe(`${CONTROLLER_BASE}/artifacts/final.mp4`)
    })
  })

  it('applies preview then final when websocket events arrive', async () => {
    mockCreateAnimation.mockResolvedValue({
      conversation_id: 'conv-1',
      scene_path: '/tmp/scene.py',
      render_options: { background_color: '#fff' },
    })
    mockQueueRender.mockResolvedValue({ status: 'queued' })

    const { getByRole, getByTestId } = render(<App />)
    fireEvent.click(getByRole('button', { name: 'Generate' }))

    await waitFor(() => expect(hookState.conversationId).toBe('conv-1'))
    act(() => {
      hookState.handlers.onPreviewReady?.('/preview.mp4')
    })
    await waitFor(() => {
      const preview = getByTestId('render-video') as HTMLVideoElement
      expect(preview.getAttribute('src')).toBe(`${CONTROLLER_BASE}/preview.mp4`)
    })

    act(() => {
      hookState.handlers.onRenderReady?.('/final.mp4')
    })
    await waitFor(() => {
      const final = getByTestId('render-video') as HTMLVideoElement
      expect(final.getAttribute('src')).toBe(`${CONTROLLER_BASE}/final.mp4`)
    })
  })

  it('shows render_failed errors', async () => {
    mockCreateAnimation.mockResolvedValue({
      conversation_id: 'conv-1',
      scene_path: '/tmp/scene.py',
      render_options: { background_color: '#fff' },
    })
    mockQueueRender.mockResolvedValue({ status: 'queued' })

    const { getByRole, getByText } = render(<App />)
    fireEvent.click(getByRole('button', { name: 'Generate' }))

    await waitFor(() => expect(hookState.conversationId).toBe('conv-1'))
    act(() => {
      hookState.handlers.onRenderFailed?.({ error: 'render exploded' })
    })

    await waitFor(() => expect(getByText('render exploded')).toBeTruthy())
  })

  it('toggles the sidebar collapse state', () => {
    const { getByRole, queryByLabelText } = render(<App />)

    const collapseButton = getByRole('button', { name: 'Hide sidebar' })
    fireEvent.click(collapseButton)

    expect(queryByLabelText('Describe the animation sequence')).toBeNull()
    expect(getByRole('button', { name: 'Show sidebar' })).toBeTruthy()

    fireEvent.click(getByRole('button', { name: 'Show sidebar' }))
    expect(getByRole('textbox', { name: 'Describe the animation sequence' })).toBeTruthy()
  })
})
