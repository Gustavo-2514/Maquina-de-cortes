import type { Word } from '@/api/types'

export interface FlatWord extends Word {
  seg: number
  idx: number
}

/** Índice da palavra que está tocando em `t` (busca binária em palavras ordenadas). -1 se nenhuma. */
export function wordAt(words: Word[], t: number): number {
  let lo = 0
  let hi = words.length - 1
  while (lo <= hi) {
    const mid = (lo + hi) >> 1
    if (words[mid].e < t) lo = mid + 1
    else if (words[mid].s > t) hi = mid - 1
    else return mid
  }
  return -1
}
