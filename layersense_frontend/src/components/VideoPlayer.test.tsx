import { cleanup, render } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { VideoPlayer } from './VideoPlayer'

describe('VideoPlayer', () => {
  afterEach(() => {
    cleanup()
  })

  it('shows placeholder when no media is available', () => {
    const { getByText, queryByTestId } = render(
      <VideoPlayer previewUrl={null} finalUrl={null} error={null} status="idle" />,
    )

    expect(getByText('No render yet')).toBeTruthy()
    expect(queryByTestId('render-video')).toBeNull()
  })

  it('renders preview video without autoplay', () => {
    const { getByTestId } = render(
      <VideoPlayer previewUrl="/preview.mp4" finalUrl={null} error={null} status="waiting_for_final" />,
    )

    const video = getByTestId('render-video') as HTMLVideoElement
    expect(video.getAttribute('src')).toContain('/preview.mp4')
    expect(video.autoplay).toBe(false)
    expect(video.controls).toBe(true)
  })

  it('prefers final video source over preview', () => {
    const { getByTestId } = render(
      <VideoPlayer
        previewUrl="/preview.mp4"
        finalUrl="/final.mp4"
        error={null}
        status="complete"
      />,
    )

    const video = getByTestId('render-video') as HTMLVideoElement
    expect(video.getAttribute('src')).toContain('/final.mp4')
  })

  it('shows error state when render fails', () => {
    const { getByText } = render(
      <VideoPlayer previewUrl={null} finalUrl={null} error="Render failed" status="error" />,
    )

    expect(getByText('Render failed')).toBeTruthy()
  })

  it('keeps preview visible when an error arrives after preview is ready', () => {
    const { getByTestId, getByText } = render(
      <VideoPlayer
        previewUrl="/preview.mp4"
        finalUrl={null}
        error="Final render failed"
        status="error"
      />,
    )

    const video = getByTestId('render-video') as HTMLVideoElement
    expect(video.getAttribute('src')).toContain('/preview.mp4')
    expect(getByText('Final render failed')).toBeTruthy()
  })
})
