import { beforeEach, describe, expect, it } from 'vitest'
import type { Clip } from '@/api/types'
import { draftFromClip, patchDiff, useEditor } from './editor'

const clip = {
  id: 1, project_id: 1, title: 'T', hook_text: '', reason: '', start_s: 10, end_s: 40, score: 80,
  score_breakdown_json: '{}', status: 'suggested', origin: 'ai', reframe_mode: 'auto', manual_crop_json: '[]',
  caption_style_id: null, caption_overrides_json: '{"12.000": "oi"}', export_json: '{}', layout_json: '{}', title_overlay: '',
  output_path: '', error: '', rendered_at: null, created_at: '', updated_at: '',
} as unknown as Clip

describe('editor store', () => {
  beforeEach(() => useEditor.getState().load(clip))

  it('lê o formato antigo de correções', () => {
    expect(draftFromClip(clip).words).toEqual({ '12.000': 'oi' })
  })

  it('desfazer/refazer', () => {
    const s = useEditor.getState()
    s.set({ start_s: 11 })
    s.set({ end_s: 41 })
    expect(useEditor.getState().draft?.end_s).toBe(41)
    useEditor.getState().undo()
    expect(useEditor.getState().draft).toMatchObject({ start_s: 11, end_s: 40 })
    useEditor.getState().undo()
    expect(useEditor.getState().draft?.start_s).toBe(10)
    useEditor.getState().redo()
    expect(useEditor.getState().draft?.start_s).toBe(11)
  })

  it('agrupa edições seguidas do mesmo controle e gestos', () => {
    const s = useEditor.getState()
    s.set({ title: 'a' }, 'title')
    s.set({ title: 'ab' }, 'title')
    s.set({ title: 'abc' }, 'title')
    expect(useEditor.getState().past).toHaveLength(1)
    s.checkpoint()
    s.set({ start_s: 12 }, 'gesture')
    s.set({ start_s: 13 }, 'gesture')
    useEditor.getState().undo()
    expect(useEditor.getState().draft).toMatchObject({ title: 'abc', start_s: 10 })
  })

  it('diff só com o que mudou', () => {
    const { saved } = useEditor.getState()
    useEditor.getState().set({ end_s: 35, style: { font_size: 100 } })
    const diff = patchDiff(saved, useEditor.getState().draft!)
    expect(Object.keys(diff).sort()).toEqual(['caption_overrides_json', 'end_s'])
    expect(JSON.parse(diff.caption_overrides_json as string).style).toEqual({ font_size: 100 })
  })
})
