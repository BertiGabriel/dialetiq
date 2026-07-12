"""HTTP entrypoint: the admin panel API and the mobile app API.

One image, several entrypoints. This one serves HTTP; siblings run the queues.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI

from dialetiq.platform.db import guards
from dialetiq.platform.db.session import _engine
from dialetiq.platform.observability.logging import configure_logging

log = structlog.get_logger()


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    configure_logging()

    # Refuse to serve traffic on a database that cannot isolate tenants.
    #
    # This has to happen at boot, not in a nightly job: the failure modes it
    # catches (an app role granted BYPASSRLS, a new table shipped without RLS)
    # are silent. Everything works, all tests pass, and every tenant can read
    # every other tenant's data. A crashing pod is a far better outcome than a
    # healthy one serving a cross-tenant leak.
    async with _engine.connect() as conn:
        await guards.run_all(conn)

    log.info("startup.database_guards_passed")
    yield


app = FastAPI(title="Dialetiq", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
