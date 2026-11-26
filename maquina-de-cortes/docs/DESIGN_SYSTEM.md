# Design system — Máquina de Cortes

**Português** · [English](DESIGN_SYSTEM.en.md)

Minimalista, em preto e branco, com um único vermelho. A referência é a escola suíça e o design industrial
(Braun, Nothing, Teenage Engineering, Vercel): poucas peças, cada uma com função, e uma cor que só aparece
quando importa. A interface fica quieta para o vídeo ser o protagonista.

Os tokens moram em [`frontend/src/index.css`](../frontend/src/index.css). Nenhum componente deve usar hex
solto nem cores do Tailwind (`zinc-*`, `amber-*`…): use sempre os tokens abaixo.

## Cores

São três, e não existe uma quarta.

| Token   | Hex       | Papel |
|---------|-----------|-------|
| Preto   | `#000000` | Fundo de tudo: página, barra lateral, cartões, diálogos. |
| Branco  | `#ffffff` | Texto, ícones, linhas e estados neutros. |
| Corte   | `#df2531` | Destaque: ação principal, item ativo, seleção, foco, erro. |

**Tons intermediários são branco com transparência sobre o preto**, nunca um cinza novo:

| Uso | Valor | Classe |
|-----|-------|--------|
| Texto secundário | branco 60% | `text-muted-foreground` |
| Linha fina (bordas, divisores) | branco 12% | `border` (padrão) |
| Borda de campo | branco 18% | `border-input` |
| Preenchimento leve (hover, chip) | branco 7–8% | `bg-accent`, `bg-secondary`, `bg-muted` |

### Regras do vermelho

- **Uma ação principal por tela.** Só o botão que faz a coisa principal (`Criar cortes`, `Exportar`) é vermelho.
  Os demais são `outline`, `secondary` ou `ghost`.
- **Vermelho marca o que está selecionado ou ativo**: item atual do menu, trecho selecionado na linha do tempo,
  preset de legenda escolhido, foco do teclado.
- **Vermelho também é erro.** Como o destaque e o erro dividem a cor, erros sempre vêm com ícone e texto explicando
  o que aconteceu. Nunca dependa só da cor.
- Cortes com nota alta (≥ 80) ganham selo vermelho cheio: são o destaque do projeto.
- Barras de progresso são **brancas**: progresso é informação, não chamada para ação.

### Estados sem cor

Sucesso e aviso não têm cor própria. O ícone e o texto carregam o significado:

| Estado | Tratamento |
|--------|------------|
| Sucesso / concluído | branco, ícone de check, etapa concluída com círculo branco cheio |
| Aviso / opcional | branco 75%, ícone de alerta, badge com borda tracejada |
| Erro / destrutivo | vermelho, ícone de X ou alerta |

No editor, as áreas de enquadramento usam o traço para se diferenciar: webcam com linha contínua branca,
jogo com linha tracejada branca, área ativa em vermelho.

## Tipografia

**Poppins** em tudo, carregada localmente via `@fontsource/poppins` (o app funciona offline). Pesos usados:

| Peso | Uso |
|------|-----|
| 400 | Texto corrido |
| 500 | Botões, rótulos, itens de lista |
| 600 | Títulos (`font-display`, com `letter-spacing: -0.03em`) |
| 700 | Reservado; evite |

Escala (rem sobre 16 px): `xs 12` · `sm 14` · `base 16` · `lg 18` · `xl 20` · `2xl 25` · `3xl 31` · `4xl 39` · `5xl 49`.
Do `xl` para cima a escala segue a terça maior (×1,25). Linhas de texto com no máximo ~70 caracteres (`max-w-prose`, `max-w-md`).

As fontes das **legendas** dos cortes (Montserrat, Inter, Bebas Neue) são conteúdo do vídeo, não da interface,
e ficam fora deste sistema.

## Forma

- **Sem sombras.** Profundidade vem de linha fina e de espaço.
- **Superfícies são pretas.** Cartões e diálogos se separam do fundo só pela borda de 1 px.
- **Raios com hierarquia:** 4 px (miniaturas, tags), 6 px (botões, campos), 10 px (cartões), 14 px (diálogos e mídia de destaque),
  totalmente redondo só para indicadores (contadores, pontos de status, badges).
- **Botões:** 36 px de altura (44 px no `lg`), peso 500, sem caixa alta.
- **Foco:** anel vermelho de 2 px com afastamento de 2 px, sempre visível no teclado.

## Imagem e movimento

- Ilustrações e mídia da marca aparecem em **escala de cinza** (`grayscale`) para não competir com o vermelho.
  Miniaturas e vídeos do usuário continuam coloridos: são o conteúdo.
- Movimento só responde a uma ação (abrir, confirmar, arrastar). A única exceção é a **entrada do hero da Início**,
  uma vez no carregamento (`enter`, escalonado por `--enter-delay`). Nada de animações de entrada por seção ou na rolagem.
- Microinterações (utilidades em `index.css`, só `transform`/`opacity`):

  | Utilidade | Onde | O que faz |
  |-----------|------|-----------|
  | botão (`Button`) | todo botão | muda o fundo no hover e afunda para 97% no clique |
  | `lift` | card com link | sobe 2 px no hover |
  | `zoom-in-frame` | foto dentro de card `.group` | aproxima 2% dentro da moldura |
  | `link-draw` | link de texto | o sublinhado se desenha da esquerda para a direita |

- Loop decorativo com mais de 5 s (o vídeo do hero) tem botão de pausa.
- `prefers-reduced-motion` zera todas as durações.

## Interação e acessibilidade

Seguimos as [Web Interface Guidelines da Vercel](https://github.com/vercel-labs/web-interface-guidelines). O essencial:

- Link "Pular para o conteúdo" como primeiro item do Tab; foco sempre visível.
- Botão principal fica habilitado até o envio começar; a validação explica o que falta.
- Placeholders terminam em "…"; campos com `type`, `name`, `autocomplete` e `spellCheck` corretos.
- Aspas curvas (“ ”) e reticências (…) no texto; `text-wrap: balance` nos títulos.
- Imagens com `width`/`height`; abaixo da dobra, `loading="lazy"`.
- Erro diz o que houve **e o que fazer** (componente `LoadError`).
- Abaixo de 768 px a barra lateral vira só ícones.

## Texto

Frases curtas, verbo no imperativo e em caixa normal. O botão diz o que acontece (`Criar cortes`, não `Enviar`).
Sem rótulos em CAIXA ALTA acima de títulos e sem numeração decorativa: números só onde há sequência real
(os três passos de "Como funciona").
