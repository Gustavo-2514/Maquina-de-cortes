"""Presets de legenda embutidos (seção 8.6), criados/atualizados no start."""

from __future__ import annotations

from sqlmodel import Session, select

BUILTIN: list[dict] = [
    {"key": "hormozi", "name": "Hormozi", "font": "Montserrat ExtraBold", "font_size": 92, "primary_color": "#FFFFFF",
     "highlight_color": "#FFE600", "outline_color": "#000000", "outline_px": 6, "shadow_px": 0, "uppercase": True,
     "words_per_line": 2, "position_y": 0.68, "animation": "highlight"},
    {"key": "clean", "name": "Clean", "font": "Inter", "font_size": 64, "primary_color": "#FFFFFF",
     "highlight_color": "#FFFFFF", "outline_color": "#000000", "outline_px": 0, "shadow_px": 3, "uppercase": False,
     "words_per_line": 4, "position_y": 0.72, "animation": "none"},
    {"key": "neon", "name": "Neon", "font": "Montserrat Black", "font_size": 88, "primary_color": "#FFFFFF",
     "highlight_color": "#39FF14", "outline_color": "#000000", "outline_px": 5, "shadow_px": 0, "uppercase": True,
     "words_per_line": 2, "position_y": 0.66, "animation": "pop"},
    {"key": "karaoke", "name": "Karaokê", "font": "Montserrat ExtraBold", "font_size": 76, "primary_color": "#FFFFFF",
     "highlight_color": "#00D1FF", "outline_color": "#000000", "outline_px": 5, "shadow_px": 0, "uppercase": True,
     "words_per_line": 3, "position_y": 0.68, "animation": "karaoke"},
    {"key": "impacto", "name": "Impacto", "font": "Bebas Neue", "font_size": 150, "primary_color": "#FFFFFF",
     "highlight_color": "#FF3B30", "outline_color": "#000000", "outline_px": 6, "shadow_px": 4, "uppercase": True,
     "words_per_line": 1, "position_y": 0.62, "animation": "pop"},
    {"key": "minimal", "name": "Minimal", "font": "Inter SemiBold", "font_size": 62, "primary_color": "#FFFFFF",
     "highlight_color": "#FFFFFF", "outline_color": "#000000", "outline_px": 0, "shadow_px": 2, "uppercase": False,
     "words_per_line": 4, "position_y": 0.8, "animation": "none"},
    {"key": "amarelo", "name": "Amarelo", "font": "Montserrat Black", "font_size": 84, "primary_color": "#FFE600",
     "highlight_color": "#FFFFFF", "outline_color": "#000000", "outline_px": 6, "shadow_px": 0, "uppercase": True,
     "words_per_line": 2, "position_y": 0.66, "animation": "pop"},
]


def seed_builtin_styles() -> None:
    from ..db import engine
    from ..models import CaptionStyle

    with Session(engine) as s:
        existing = {c.key for c in s.exec(select(CaptionStyle).where(CaptionStyle.is_builtin == True)).all()}  # noqa: E712
        for d in BUILTIN:
            if d["key"] not in existing:
                s.add(CaptionStyle(**d, is_builtin=True))
        s.commit()


def style_for_clip(session: Session, caption_style_id: int | None, fallback_key: str):
    from ..models import CaptionStyle

    style = session.get(CaptionStyle, caption_style_id) if caption_style_id else None
    if style is None:
        style = session.exec(select(CaptionStyle).where(CaptionStyle.key == fallback_key)).first()
    if style is None:
        style = session.exec(select(CaptionStyle).where(CaptionStyle.key == "hormozi")).first()
    return style
