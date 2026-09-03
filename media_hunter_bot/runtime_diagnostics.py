"""Runtime diagnostics for tracing media jobs without changing processing semantics."""
from __future__ import annotations

import logging
import time
from functools import wraps

logger = logging.getLogger("media_hunter_bot.pipeline")


def patch_engine(engine_cls):
    """Add timing logs around queue insertion and job execution once."""
    if getattr(engine_cls, "_pipeline_diagnostics_patched", False):
        return

    original_add = engine_cls.add
    original_run_job = engine_cls._run_job

    @wraps(original_add)
    async def add(self, uid, url=None, source=None):
        started = time.monotonic()
        logger.info(
            "QUEUE_ADD_START uid=%s kind=%s",
            uid,
            "url" if url else "upload" if source else "unknown",
        )
        try:
            result = await original_add(self, uid, url=url, source=source)
            logger.info(
                "QUEUE_ADD_DONE uid=%s queue_size=%s elapsed_ms=%d",
                uid,
                getattr(self, "_queue_size", "?"),
                int((time.monotonic() - started) * 1000),
            )
            return result
        except Exception:
            logger.exception("QUEUE_ADD_FAILED uid=%s elapsed_ms=%d", uid, int((time.monotonic() - started) * 1000))
            raise

    @wraps(original_run_job)
    async def run_job(self, job):
        started = time.monotonic()
        logger.info(
            "JOB_START uid=%s seq=%s priority=%s kind=%s",
            job.uid,
            job.seq,
            job.priority,
            "url" if job.url else "upload",
        )
        try:
            result = await original_run_job(self, job)
            logger.info(
                "JOB_DONE uid=%s seq=%s elapsed_ms=%d",
                job.uid,
                job.seq,
                int((time.monotonic() - started) * 1000),
            )
            return result
        except Exception:
            logger.exception(
                "JOB_EXCEPTION uid=%s seq=%s elapsed_ms=%d",
                job.uid,
                job.seq,
                int((time.monotonic() - started) * 1000),
            )
            raise

    engine_cls.add = add
    engine_cls._run_job = run_job
    engine_cls._pipeline_diagnostics_patched = True


def patch_bot_downloads(bot_cls):
    """Trace Local Bot API file retrieval/download latency."""
    if getattr(bot_cls, "_pipeline_download_diagnostics_patched", False):
        return

    original_get_file = bot_cls.get_file
    original_download_file = bot_cls.download_file

    @wraps(original_get_file)
    async def get_file(self, *args, **kwargs):
        started = time.monotonic()
        file_id = args[0] if args else kwargs.get("file_id", "?")
        logger.info("TELEGRAM_GET_FILE_START file_id=%s", file_id)
        try:
            result = await original_get_file(self, *args, **kwargs)
            logger.info("TELEGRAM_GET_FILE_DONE file_id=%s path=%s elapsed_ms=%d", file_id, getattr(result, "file_path", "?"), int((time.monotonic() - started) * 1000))
            return result
        except Exception:
            logger.exception("TELEGRAM_GET_FILE_FAILED file_id=%s elapsed_ms=%d", file_id, int((time.monotonic() - started) * 1000))
            raise

    @wraps(original_download_file)
    async def download_file(self, *args, **kwargs):
        started = time.monotonic()
        file_path = args[0] if args else kwargs.get("file_path", "?")
        logger.info("TELEGRAM_DOWNLOAD_START path=%s", file_path)
        try:
            result = await original_download_file(self, *args, **kwargs)
            logger.info("TELEGRAM_DOWNLOAD_DONE path=%s elapsed_ms=%d", file_path, int((time.monotonic() - started) * 1000))
            return result
        except Exception:
            logger.exception("TELEGRAM_DOWNLOAD_FAILED path=%s elapsed_ms=%d", file_path, int((time.monotonic() - started) * 1000))
            raise

    bot_cls.get_file = get_file
    bot_cls.download_file = download_file
    bot_cls._pipeline_download_diagnostics_patched = True
