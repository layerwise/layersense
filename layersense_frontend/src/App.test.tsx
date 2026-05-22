import { cleanup, fireEvent, render, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { CONTROLLER_BASE } from './api'
import App from './App'

const mockCreateAnimation = vi.fn()
const mockQueueRender = vi.fn()
const mockUseRenderJob = vi.fn()

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

vi.mock('./hooks/useRenderJob', () => ({
  useRenderJob: (...args: unknown[]) => mockUseRenderJob(...args),
}))

describe('App', () => {
  afterEach(() => {
    cleanup()
  })

  beforeEach(() => {
    mockCreateAnimation.mockReset()
    mockQueueRender.mockReset()
    mockUseRenderJob.mockReset()
    mockUseRenderJob.mockReturnValue(null)
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
      source_code: 'code', content_hash: 'hash',
    })
    await waitFor(() => expect(mockQueueRender).toHaveBeenCalledTimes(1))
    expect(button.disabled).toBe(true)

    resolveQueue!({
      job_id: 'job-1',
      job: {
        job_id: 'job-1',
        conversation_id: 'conv-1',
        status: 'queued',
        version: 1,
        preview_url: null,
        final_url: null,
        error: null,
        stderr: null,
      },
    })
    await waitFor(() => expect(button.disabled).toBe(false))
  })

  it('sends prompt and scene snapshot to createAnimation', async () => {
    mockCreateAnimation.mockResolvedValue({
      conversation_id: 'conv-1',
      source_code: 'code', content_hash: 'hash',
    })
    mockQueueRender.mockResolvedValue({
      job_id: 'job-1',
      job: {
        job_id: 'job-1',
        conversation_id: 'conv-1',
        status: 'queued',
        version: 1,
        preview_url: null,
        final_url: null,
        error: null,
        stderr: null,
      },
    })

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
        source_code: 'code-1', content_hash: 'hash-1',
      })
      .mockResolvedValueOnce({
        conversation_id: 'conv-2',
        source_code: 'code-2', content_hash: 'hash-2',
      })
    mockQueueRender.mockResolvedValue({
      job_id: 'job-1',
      job: {
        job_id: 'job-1',
        conversation_id: 'conv-1',
        status: 'queued',
        version: 1,
        preview_url: null,
        final_url: null,
        error: null,
        stderr: null,
      },
    })

    const { getByRole } = render(<App />)
    const button = getByRole('button', { name: 'Generate' })

    fireEvent.click(button)
    await waitFor(() =>
      expect(mockQueueRender).toHaveBeenCalledWith({
        source_code: 'code-1', content_hash: 'hash-1',
        conversation_id: 'conv-1',
        cli_flags: {},
      }),
    )

    fireEvent.click(button)
    await waitFor(() =>
      expect(mockQueueRender).toHaveBeenCalledWith({
        source_code: 'code-2', content_hash: 'hash-2',
        conversation_id: 'conv-2',
        cli_flags: {},
      }),
    )
  })

  it('queues renders with empty controller cli flags by default', async () => {
    mockCreateAnimation.mockResolvedValue({
      conversation_id: 'conv-null-bg',
      source_code: 'code-null', content_hash: 'hash-null',
    })
    mockQueueRender.mockResolvedValue({
      job_id: 'job-null-bg',
      job: {
        job_id: 'job-null-bg',
        conversation_id: 'conv-null-bg',
        status: 'queued',
        version: 1,
        preview_url: null,
        final_url: null,
        error: null,
        stderr: null,
      },
    })

    const { getByRole } = render(<App />)
    fireEvent.click(getByRole('button', { name: 'Generate' }))

    await waitFor(() =>
      expect(mockQueueRender).toHaveBeenCalledWith({
        source_code: 'code-null', content_hash: 'hash-null',
        conversation_id: 'conv-null-bg',
        cli_flags: {},
      }),
    )
  })

  it('shows preview then final as polled job snapshots advance', async () => {
    mockCreateAnimation.mockResolvedValue({
      conversation_id: 'conv-1',
      source_code: 'code', content_hash: 'hash',
    })
    mockQueueRender.mockResolvedValue({
      job_id: 'job-1',
      job: {
        job_id: 'job-1',
        conversation_id: 'conv-1',
        status: 'queued',
        version: 1,
        preview_url: null,
        final_url: null,
        error: null,
        stderr: null,
      },
    })

    let activeCalls = 0
    mockUseRenderJob.mockImplementation(({ jobId }: { jobId: string | null }) => {
      if (!jobId) {
        return null
      }

      activeCalls += 1
      if (activeCalls === 1) {
        return {
          job_id: 'job-1',
          conversation_id: 'conv-1',
          status: 'waiting_for_final',
          version: 2,
          preview_url: '/preview.mp4',
          final_url: null,
          error: null,
          stderr: null,
        }
      }

      return {
        job_id: 'job-1',
        conversation_id: 'conv-1',
        status: 'succeeded',
        version: 3,
        preview_url: '/preview.mp4',
        final_url: '/final.mp4',
        error: null,
        stderr: null,
      }
    })

    const { getByRole, getByTestId, rerender } = render(<App />)
    fireEvent.click(getByRole('button', { name: 'Generate' }))

    await waitFor(() => {
      const preview = getByTestId('render-video') as HTMLVideoElement
      expect(preview.getAttribute('src')).toBe(`${CONTROLLER_BASE}/preview.mp4`)
    })

    rerender(<App />)
    await waitFor(() => {
      const final = getByTestId('render-video') as HTMLVideoElement
      expect(final.getAttribute('src')).toBe(`${CONTROLLER_BASE}/final.mp4`)
    })
  })

  it('uses controller base URL for cached artifact video sources', async () => {
    mockCreateAnimation.mockResolvedValue({
      conversation_id: 'conv-1',
      source_code: 'code', content_hash: 'hash',
    })
    mockQueueRender.mockResolvedValue({
      job_id: 'job-1',
      job: {
        job_id: 'job-1',
        conversation_id: 'conv-1',
        status: 'succeeded',
        version: 1,
        preview_url: '/artifacts/preview.mp4',
        final_url: '/artifacts/final.mp4',
        error: null,
        stderr: null,
      },
    })

    const { getByRole, getByTestId } = render(<App />)
    fireEvent.click(getByRole('button', { name: 'Generate' }))

    await waitFor(() => {
      const video = getByTestId('render-video') as HTMLVideoElement
      expect(video.getAttribute('src')).toBe(`${CONTROLLER_BASE}/artifacts/final.mp4`)
    })
  })

  it('shows failed job errors', async () => {
    mockCreateAnimation.mockResolvedValue({
      conversation_id: 'conv-1',
      source_code: 'code', content_hash: 'hash',
    })
    mockQueueRender.mockResolvedValue({
      job_id: 'job-1',
      job: {
        job_id: 'job-1',
        conversation_id: 'conv-1',
        status: 'failed',
        version: 2,
        preview_url: null,
        final_url: null,
        error: 'render exploded',
        stderr: '',
      },
    })
    mockUseRenderJob.mockImplementation(({ jobId }: { jobId: string | null }) => {
      if (!jobId) {
        return null
      }

      return {
        job_id: 'job-1',
        conversation_id: 'conv-1',
        status: 'failed',
        version: 2,
        preview_url: null,
        final_url: null,
        error: 'render exploded',
        stderr: '',
      }
    })

    const { getByRole, getByText } = render(<App />)
    fireEvent.click(getByRole('button', { name: 'Generate' }))

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
