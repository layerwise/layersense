import { createRef } from 'react'
import { render } from '@testing-library/react'
import { describe, expect, it, vi, beforeEach } from 'vitest'

import { Canvas, type CanvasHandle } from './Canvas'

const mockApi = {
  getSceneElements: vi.fn(() => [{ id: 'element-1' }]),
  getAppState: vi.fn(() => ({ viewBackgroundColor: '#fff' })),
  getFiles: vi.fn(() => ({ file1: { id: 'file1' } })),
}

vi.mock('@excalidraw/excalidraw', () => ({
  Excalidraw: ({ excalidrawAPI }: { excalidrawAPI?: (api: unknown) => void }) => {
    excalidrawAPI?.(mockApi)
    return <div data-testid="excalidraw-canvas" />
  },
}))

describe('Canvas', () => {
  beforeEach(() => {
    mockApi.getSceneElements.mockClear()
    mockApi.getAppState.mockClear()
    mockApi.getFiles.mockClear()
  })

  it('renders Excalidraw container', () => {
    const ref = createRef<CanvasHandle>()
    const { getByTestId } = render(<Canvas ref={ref} />)
    expect(getByTestId('canvas-host')).toBeTruthy()
    expect(getByTestId('excalidraw-canvas')).toBeTruthy()
  })

  it('exposes deterministic scene snapshot via ref', () => {
    const ref = createRef<CanvasHandle>()
    render(<Canvas ref={ref} />)

    const snapshot = ref.current?.getSceneSnapshot()

    expect(snapshot).toEqual({
      elements: [{ id: 'element-1' }],
      appState: { viewBackgroundColor: '#fff' },
      files: { file1: { id: 'file1' } },
    })
    expect(mockApi.getSceneElements).toHaveBeenCalledTimes(1)
    expect(mockApi.getAppState).toHaveBeenCalledTimes(1)
    expect(mockApi.getFiles).toHaveBeenCalledTimes(1)
  })
})
