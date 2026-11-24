import { describe, expect, it } from 'vitest'
import { cropWidth, manualCx, singleCrop, snapEnd, snapStart, splitBox, trackAt, type CropTrack } from './crop'

describe('crop', () => {
  it('largura 9:16 (igual ao Python)', () => {
    expect(cropWidth(1920, 1080)).toBe(606)
    expect(cropWidth(1280, 720)).toBe(404)
    expect(cropWidth(1080, 1920)).toBe(1080)
  })
  it('crop simples nunca sai do quadro', () => {
    expect(singleCrop(1920, 1080, 0).x).toBe(0)
    expect(singleCrop(1920, 1080, 1).x).toBe(1920 - 606)
    expect(singleCrop(1920, 1080, 0.5).x).toBe(657)
  })
  it('split_box dentro do quadro e com proporção 1080:960', () => {
    for (const [fx, fy] of [
      [0, 0],
      [1, 1],
      [0.5, 0.5],
    ]) {
      const r = splitBox(1280, 720, fx, fy)
      expect(r.x).toBeGreaterThanOrEqual(0)
      expect(r.x + r.w).toBeLessThanOrEqual(1280)
      expect(r.y + r.h).toBeLessThanOrEqual(720)
      expect(Math.abs(r.w / r.h - 1080 / 960)).toBeLessThan(0.01)
    }
  })
  it('trackAt usa o frame certo e limita nas pontas', () => {
    const tr: CropTrack = {
      mode: 'auto', fps: 10, src_w: 1920, src_h: 1080, frames: 3, crop_w: 606, crop_w_norm: 0.3156, cuts: [],
      layout: [0, 0, 1], cx: [0.2, 0.3, 0.5], split: [null, null, [0.2, 0.4, 0.8, 0.4]],
    }
    expect(trackAt(tr, 0.15)).toEqual({ kind: 'single', cx: 0.3 })
    expect(trackAt(tr, -5)).toEqual({ kind: 'single', cx: 0.2 })
    expect(trackAt(tr, 99)).toEqual({ kind: 'split', a: [0.2, 0.4], b: [0.8, 0.4] })
  })
  it('keyframes manuais com easing', () => {
    const kf = [
      { t: 0, x: 0.3 },
      { t: 2, x: 0.7 },
    ]
    expect(manualCx(kf, 0)).toBe(0.3)
    expect(manualCx(kf, 1)).toBeCloseTo(0.5)
    expect(manualCx(kf, 0.5)).toBeLessThan(0.4)
    expect(manualCx(kf, 5)).toBe(0.7)
  })
})

describe('encaixe nas palavras', () => {
  const words = [
    { s: 1, e: 1.4 },
    { s: 1.5, e: 2 },
    { s: 3, e: 3.4 },
  ]
  it('início e fim', () => {
    expect(snapStart(words, 1.3)).toBe(1.5)
    expect(snapEnd(words, 2.2)).toBeCloseTo(2.15)
    expect(snapEnd(words, 1.45)).toBeCloseTo(1.48) // respiro limitado pela próxima palavra
    expect(snapEnd(words, 3.5, 3.45)).toBe(3.45) // não passa do vídeo
  })
})

describe('gameplay (espelho do Python)', () => {
  it('webcam contém o rosto, proporções dos painéis e jogo centralizado', async () => {
    const { gameplayBoxes } = await import('./crop')
    const g = gameplayBoxes(1920, 1080, [0.86, 0.78, 0.05, 0.09])
    const [x, y, w, h] = g.cam!
    expect(x <= 0.86 && 0.86 <= x + w && y <= 0.78 && 0.78 <= y + h).toBe(true)
    const topH = Math.round(g.top_ratio * 1920)
    expect(Math.abs((w * 1920) / (h * 1080) - 1080 / topH)).toBeLessThan(0.02)
    expect(Math.abs(g.game[0] + g.game[2] / 2 - 0.5)).toBeLessThan(0.01)
    const g2 = gameplayBoxes(1920, 1080, [0.86, 0.78, 0.05, 0.09], { top_ratio: 0.5, cam_center: [0.2, 0.3], cam_w: 0.2, game_cx: 0.3 })
    expect(g2.top_ratio).toBe(0.5)
    expect(Math.abs(g2.cam![0] + g2.cam![2] / 2 - 0.2)).toBeLessThan(0.01)
    expect(gameplayBoxes(1920, 1080, null).cam).toBeNull()
  })
})
