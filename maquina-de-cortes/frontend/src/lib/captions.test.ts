import { describe, expect, it } from 'vitest'
import fixture from '../../../backend/tests/fixtures/captions_cases.json'
import { captionSpans, clipWords, groupLines, spanAt } from './captions'

describe('legendas: mesmos casos do backend', () => {
  for (const c of fixture.cases) {
    it(c.name, () => {
      expect(groupLines(c.words, c.words_per_line).map((l) => l.map((w) => w.w))).toEqual(c.lines)
      expect(captionSpans(c.words, c.words_per_line, c.animation, c.duration)).toEqual(c.spans)
    })
  }
})

describe('clipWords', () => {
  const words = [
    { w: 'antes', s: 9, e: 9.8 },
    { w: 'Olá', s: 10, e: 10.4 },
    { w: 'mundo.', s: 10.5, e: 11 },
    { w: 'depois', s: 20.5, e: 21 },
  ]
  it('tempos relativos e correções', () => {
    expect(clipWords(words, 10, 20, { '10.500': 'planeta.' })).toEqual([
      { w: 'Olá', s: 0, e: 0.4 },
      { w: 'planeta.', s: 0.5, e: 1 },
    ])
    expect(clipWords(words, 10, 20, { '10.000': '' }).map((w) => w.w)).toEqual(['mundo.'])
  })
})

describe('spanAt', () => {
  const spans = captionSpans(
    [
      { w: 'a', s: 0, e: 0.4 },
      { w: 'b', s: 0.5, e: 0.9 },
      { w: 'c', s: 3, e: 3.4 },
    ],
    2,
    'highlight',
    5,
  )
  it('acha o span e respeita buracos', () => {
    expect(spanAt(spans, 0.1)?.current).toBe(0)
    expect(spanAt(spans, 0.6)?.current).toBe(1)
    expect(spanAt(spans, 2)).toBeNull()
    expect(spanAt(spans, 3.1)?.line).toEqual(['c'])
  })
})
