"""Templates por tipo de conteúdo: enquadramento + o que a IA procura + legenda + nota.

Um template é escolhido ao configurar a análise (vira o padrão dos cortes) e pode ser reaplicado a todos os
cortes antes de renderizar. Cada corte ainda pode ser ajustado individualmente no editor.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class Template:
    key: str
    name: str
    description: str
    reframe_mode: str  # auto | speaker | split | gameplay | blur_fit | center
    caption_style: str  # preset padrão (key)
    caption_position_y: float | None  # None = a do preset
    prompt: str  # instruções extras para a IA (somadas às do usuário)
    caption_font_size: int | None = None  # None = a do preset (menor no gameplay para não cobrir o jogo)
    loudness_hints: bool = False  # marca falas com volume alto na transcrição enviada à IA
    llm_weight: float = 0.75  # nota = llm_weight × IA + (1 − llm_weight) × heurística
    heuristic: str = "speech"  # speech (ritmo/silêncio/energia) | reactions (picos de volume)
    tips: list[str] = field(default_factory=list)

    def to_json(self) -> dict:
        return asdict(self)


TEMPLATES: dict[str, Template] = {t.key: t for t in [
    Template(
        key="geral", name="Geral", description="Segue o rosto principal de cada cena.",
        reframe_mode="auto", caption_style="hormozi", caption_position_y=None, prompt="",
    ),
    Template(
        key="gameplay", name="Gameplay",
        description="Webcam do streamer em cima (faixa menor), jogo grande embaixo. A IA procura jogadas e reações decisivas.",
        # legenda baixa e menor: fica sobre a parte de baixo do jogo, longe da divisão com a webcam
        reframe_mode="gameplay", caption_style="hormozi", caption_position_y=0.82, caption_font_size=70,
        prompt=(
            "Este vídeo é uma GAMEPLAY com o streamer narrando. Priorize: jogadas decisivas (clutch, virada, vitória, "
            "kill múltipla, jogada improvável), falhas engraçadas, sustos e REAÇÕES FORTES do streamer (gritos, risadas, "
            "comemoração, raiva). Falas marcadas com [VOLUME ALTO] costumam ser reações — use como pista. "
            "O corte deve começar um pouco antes do lance e terminar logo depois da reação."
        ),
        loudness_hints=True, llm_weight=0.6, heuristic="reactions",
        tips=["Se a webcam não for detectada, ajuste o retângulo no editor (aba Enquadrar)."],
    ),
    Template(
        key="podcast", name="Podcast", description="Quem está falando fica no centro; troca de pessoa com corte seco.",
        reframe_mode="speaker", caption_style="hormozi", caption_position_y=0.7,
        prompt=(
            "Este vídeo é um PODCAST/entrevista. Priorize opiniões fortes, histórias pessoais com desfecho, conselhos "
            "práticos, frases de impacto e momentos engraçados entre os participantes."
        ),
    ),
    Template(
        key="debate", name="Debate", description="Tela dividida: uma pessoa em cima e a outra embaixo.",
        reframe_mode="split", caption_style="hormozi", caption_position_y=0.5,
        prompt=(
            "Este vídeo é um DEBATE/discussão. Priorize confrontos diretos, réplicas afiadas, discordâncias claras, "
            "perguntas difíceis e respostas que viram o jogo. O corte deve conter a provocação E a resposta."
        ),
    ),
]}

DEFAULT_TEMPLATE = "geral"


def get_template(key: str | None) -> Template:
    return TEMPLATES.get(key or DEFAULT_TEMPLATE, TEMPLATES[DEFAULT_TEMPLATE])
