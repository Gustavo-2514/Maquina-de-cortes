/** Fontes embutidas (backend/assets/fonts) com os mesmos nomes que o libass usa no render. */
/**
 * `assScale`: CSS px por unidade de "Fontsize" do ASS. O libass dimensiona a fonte pelas métricas de linha
 * do arquivo (diferentes por família), então o fator foi MEDIDO: altura do "H" renderizado pelo libass
 * (Fontsize 100, PlayRes 1080×1920) ÷ altura do "H" no navegador com font-size 100px.
 * Montserrat 45/70, Inter 60/72, Bebas Neue 54/70.
 */
export const FONTS: { family: string; file: string; label: string; assScale: number }[] = [
  { family: 'Montserrat ExtraBold', file: 'Montserrat-ExtraBold.ttf', label: 'Montserrat ExtraBold', assScale: 0.643 },
  { family: 'Montserrat Black', file: 'Montserrat-Black.ttf', label: 'Montserrat Black', assScale: 0.643 },
  { family: 'Montserrat Bold', file: 'Montserrat-Bold.ttf', label: 'Montserrat Bold', assScale: 0.634 },
  { family: 'Inter', file: 'Inter-Bold.ttf', label: 'Inter Bold', assScale: 0.833 },
  { family: 'Inter ExtraBold', file: 'Inter-ExtraBold.ttf', label: 'Inter ExtraBold', assScale: 0.833 },
  { family: 'Inter SemiBold', file: 'Inter-SemiBold.ttf', label: 'Inter SemiBold', assScale: 0.833 },
  { family: 'Bebas Neue', file: 'BebasNeue-Regular.ttf', label: 'Bebas Neue', assScale: 0.771 },
]

/** font-size CSS (em unidades do PlayRes 1080×1920) equivalente ao Fontsize do ASS. */
export function assFontPx(font: string, assSize: number): number {
  return assSize * (FONTS.find((f) => f.family === font)?.assScale ?? 0.7)
}

let registered = false
export function registerFonts() {
  if (registered || typeof document === 'undefined') return
  registered = true
  for (const f of FONTS) {
    const face = new FontFace(f.family, `url(/api/fonts/${f.file})`)
    face.load().then((loaded) => document.fonts.add(loaded)).catch(() => {})
  }
}
