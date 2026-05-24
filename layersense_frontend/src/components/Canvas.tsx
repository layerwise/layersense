import { Excalidraw } from '@excalidraw/excalidraw'
import type { ExcalidrawImperativeAPI } from '@excalidraw/excalidraw/types'
import { forwardRef, useCallback, useImperativeHandle, useRef } from 'react'

import type { ExcalidrawSceneSnapshot } from '../types'

export type CanvasHandle = {
  getSceneSnapshot: () => ExcalidrawSceneSnapshot
}

const emptySnapshot: ExcalidrawSceneSnapshot = {
  elements: [],
  appState: {},
  files: {},
}

export const Canvas = forwardRef<CanvasHandle>(function Canvas(_, ref) {
  const apiRef = useRef<ExcalidrawImperativeAPI | null>(null)

  const setApi = useCallback((api: ExcalidrawImperativeAPI) => {
    apiRef.current = api
  }, [])

  useImperativeHandle(
    ref,
    () => ({
      getSceneSnapshot: () => {
        if (!apiRef.current) {
          return emptySnapshot
        }

        return {
          elements: [...apiRef.current.getSceneElements()],
          appState: { ...apiRef.current.getAppState() },
          files: { ...apiRef.current.getFiles() },
        }
      },
    }),
    [],
  )

  return (
    <div className="absolute inset-0 [&_.excalidraw]:h-full [&_.excalidraw]:w-full" data-testid="canvas-host">
      <Excalidraw excalidrawAPI={setApi} />
    </div>
  )
})
