"""Loop do worker (processo separado): `python -m app.worker.runner`.

- Polling na tabela `job` a cada 0,5 s.
- Slot leve (I/O: download, probe) com até 2 jobs simultâneos; slot pesado (GPU) com 1 por vez.
- Cancelamento: a API marca o job como 'canceled'; o loop percebe e sinaliza o handler
  (JobContext.cancel → evento + terminate() nos subprocessos registrados).
"""

from __future__ import annotations

import logging
import signal
import time
from concurrent.futures import Future, ThreadPoolExecutor

from sqlalchemy import update
from sqlmodel import Session, col, select

from ..db import engine, init_db
from ..errors import friendly
from ..logging_setup import setup_logging
from ..models import Download, Job, now
from ..queue import claim, recover_interrupted
from .tasks import HANDLERS, JobCanceled, JobContext

POLL_INTERVAL_S = 0.5
LIGHT_SLOTS = 2
HEAVY_SLOTS = 1

log = logging.getLogger("worker")


def _finish(job_id: int, status: str, message: str, error: str = "", detail: str = "") -> None:
    values = {"status": status, "message": message, "error": error, "error_detail": detail,
              "finished_at": now(), "updated_at": now()}
    if status == "done":
        values["progress"] = 100
    with Session(engine) as s:
        # só finaliza se ainda estiver 'running' (não sobrescreve um cancelamento da API)
        s.exec(update(Job).where(col(Job.id) == job_id, col(Job.status) == "running").values(**values))  # type: ignore[call-overload]
        s.commit()


def _requeue(ctx: JobContext) -> None:
    with Session(engine) as s:
        s.exec(update(Job).where(col(Job.id) == ctx.job_id, col(Job.status) == "running")  # type: ignore[call-overload]
               .values(status="queued", progress=0, message="Interrompido; será retomado", updated_at=now()))
        if ctx.type == "download":
            s.exec(update(Download).where(col(Download.id) == ctx.ref_id)  # type: ignore[call-overload]
                   .values(status="queued", progress=0, speed="", eta="", updated_at=now()))
        s.commit()


def execute(ctx: JobContext) -> None:
    handler = HANDLERS.get(ctx.type)
    try:
        if handler is None:
            raise RuntimeError(f"Tipo de job sem handler: {ctx.type}")
        handler(ctx)
    except Exception:
        if ctx.interrupted:
            _requeue(ctx)
            log.info("job %s interrompido pelo encerramento; volta para a fila", ctx.job_id)
            return
        raise


def _execute(ctx: JobContext) -> None:
    try:
        execute(ctx)
    except JobCanceled:
        _finish(ctx.job_id, "canceled", "Cancelado")
        log.info("job %s cancelado", ctx.job_id)
    except Exception as e:  # noqa: BLE001
        if ctx.is_canceled():
            _finish(ctx.job_id, "canceled", "Cancelado")
            return
        message, detail = friendly(e)
        log.exception("job %s (%s) falhou", ctx.job_id, ctx.type)
        _finish(ctx.job_id, "error", "Erro", error=message, detail=detail[-4000:])
    else:
        _finish(ctx.job_id, "done", "Concluído")
        log.info("job %s (%s) concluído", ctx.job_id, ctx.type)


class Worker:
    def __init__(self) -> None:
        self.running = True
        self.pools = {False: ThreadPoolExecutor(LIGHT_SLOTS, "light"), True: ThreadPoolExecutor(HEAVY_SLOTS, "gpu")}
        self.slots = {False: LIGHT_SLOTS, True: HEAVY_SLOTS}
        self.active: dict[int, tuple[JobContext, Future, bool]] = {}

    def stop(self, *_a) -> None:
        self.running = False

    def tick(self) -> None:
        # limpa terminados
        for jid in [j for j, (_c, f, _g) in self.active.items() if f.done()]:
            del self.active[jid]

        with Session(engine) as s:
            # cancelamentos pedidos pela API
            if self.active:
                still_running = set(s.exec(
                    select(Job.id).where(col(Job.id).in_(list(self.active)), Job.status == "running")
                ).all())
                # cancelado pela API ou apagado (ex.: download removido) → interrompe
                for jid in set(self.active) - still_running:
                    if self.active[jid][1].done():
                        continue
                    ctx = self.active[jid][0]
                    if not ctx.is_canceled():
                        log.info("cancelando job %s", jid)
                        ctx.cancel()

            # novos jobs
            for gpu in (False, True):
                busy = sum(1 for (_c, _f, g) in self.active.values() if g == gpu)
                while busy < self.slots[gpu]:
                    job = claim(s, gpu, set(self.active))
                    if job is None:
                        break
                    ctx = JobContext(job)
                    log.info("iniciando job %s (%s ref=%s)", job.id, job.type, job.ref_id)
                    self.active[job.id] = (ctx, self.pools[gpu].submit(_execute, ctx), gpu)  # type: ignore[index]
                    busy += 1

    def run(self) -> None:
        with Session(engine) as s:
            n = recover_interrupted(s)
        if n:
            log.info("%d job(s) interrompido(s) voltaram para a fila", n)
        print("[worker] pronto (aguardando jobs)", flush=True)
        while self.running:
            try:
                self.tick()
            except Exception:  # noqa: BLE001
                log.exception("erro no loop do worker")
            time.sleep(POLL_INTERVAL_S)
        log.info("encerrando: cancelando %d job(s) ativos", len(self.active))
        for ctx, _f, _g in self.active.values():
            ctx.interrupted = True
            ctx.cancel()
        for pool in self.pools.values():
            pool.shutdown(wait=True, cancel_futures=True)


def main() -> None:
    setup_logging("worker")
    init_db()
    w = Worker()
    signal.signal(signal.SIGTERM, w.stop)
    signal.signal(signal.SIGINT, w.stop)
    log.info("worker iniciado")
    w.run()
    log.info("worker encerrado")


if __name__ == "__main__":
    main()
