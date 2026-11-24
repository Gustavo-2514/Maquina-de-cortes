"""Broker SSE: pub/sub em memória alimentado por polling do banco.

O worker é outro processo, então a API descobre mudanças lendo `updated_at` das tabelas
a cada 0,5 s e publica `<tabela>.update` para todos os inscritos em GET /api/events.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

from sqlmodel import Session, SQLModel, col, select

from .db import engine
from .models import Clip, Download, Job, Project
from .queue import job_target

log = logging.getLogger(__name__)

POLL_INTERVAL_S = 0.5
KEEPALIVE_S = 15
# tabela → nome do evento
EPOCH = datetime(2000, 1, 1, tzinfo=UTC)  # cursor inicial de tabela vazia (datetime.min - 1s estoura)
WATCHED: dict[type[SQLModel], str] = {Job: "job.update", Download: "download.update", Project: "project.update",
                                      Clip: "clip.update"}


def to_json(obj: SQLModel) -> dict:
    return json.loads(obj.model_dump_json())


class Broker:
    def __init__(self) -> None:
        self.subscribers: set[asyncio.Queue[tuple[str, dict]]] = set()
        self._task: asyncio.Task | None = None
        self._cursor: dict[type, datetime] = {}
        self._sent: dict[tuple[str, int], datetime] = {}

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._poll_loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    def publish(self, event: str, data: dict) -> None:
        for q in list(self.subscribers):
            try:
                q.put_nowait((event, data))
            except asyncio.QueueFull:
                pass  # cliente lento: perde eventos (o front revalida ao reconectar)

    def _poll_once(self) -> list[tuple[str, dict]]:
        out: list[tuple[str, dict]] = []
        with Session(engine) as s:
            for model, event in WATCHED.items():
                cur = self._cursor.get(model)
                q = select(model)
                if cur is None:
                    # primeira passada: só marca o cursor, não reenvia o histórico
                    last = s.exec(select(model.updated_at).order_by(col(model.updated_at).desc()).limit(1)).first()  # type: ignore[attr-defined]
                    self._cursor[model] = last or EPOCH
                    continue
                # janela de 1 s para trás tolera commits fora de ordem com timestamps próximos
                rows = s.exec(q.where(col(model.updated_at) > cur - timedelta(seconds=1))).all()  # type: ignore[attr-defined]
                for row in rows:
                    key = (event, row.id)
                    if self._sent.get(key) == row.updated_at:
                        continue
                    self._sent[key] = row.updated_at
                    data = to_json(row)
                    if model is Job:
                        data.update(job_target(s, row))  # type: ignore[arg-type]
                    out.append((event, data))
                    if row.updated_at > self._cursor[model]:
                        self._cursor[model] = row.updated_at
        if len(self._sent) > 5000:
            horizon = max(self._cursor.values()) - timedelta(seconds=5)
            self._sent = {k: v for k, v in self._sent.items() if v >= horizon}
        return out

    async def _poll_loop(self) -> None:
        while True:
            try:
                if self.subscribers or not self._cursor:
                    for event, data in await asyncio.to_thread(self._poll_once):
                        self.publish(event, data)
                else:
                    # ninguém ouvindo: avança cursores para não despejar tudo quando alguém conectar
                    await asyncio.to_thread(self._poll_once)
            except Exception:  # noqa: BLE001
                log.exception("erro no polling de eventos")
            await asyncio.sleep(POLL_INTERVAL_S)

    async def stream(self) -> AsyncIterator[str]:
        q: asyncio.Queue[tuple[str, dict]] = asyncio.Queue(maxsize=1000)
        self.subscribers.add(q)
        try:
            yield "retry: 2000\n\n"
            while True:
                try:
                    event, data = await asyncio.wait_for(q.get(), timeout=KEEPALIVE_S)
                except TimeoutError:
                    yield ": ping\n\n"
                    continue
                yield f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
        finally:
            self.subscribers.discard(q)


broker = Broker()
