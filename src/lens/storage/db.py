from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def normalize_url(url: str) -> str:
    """Accept postgres:// and postgresql:// URLs from providers and use the asyncpg driver."""
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+asyncpg://" + url[len(prefix) :]
    return url


class Database:
    """One engine per process. `pooled=True` suits PgBouncer/Supavisor transaction pooling."""

    def __init__(
        self,
        url: str,
        *,
        pooled: bool = False,
        echo: bool = False,
        rollback_only: bool = False,
        read_only: bool = False,
    ) -> None:
        self.rollback_only = rollback_only or read_only
        self.read_only = read_only
        connect_args: dict[str, object] = {
            "server_settings": {"application_name": "goldirham-lens"}
        }
        if pooled:
            connect_args["statement_cache_size"] = 0
            connect_args["prepared_statement_cache_size"] = 0
        self.engine: AsyncEngine = create_async_engine(
            normalize_url(url),
            echo=echo,
            pool_pre_ping=True,
            pool_size=2 if pooled else 5,
            max_overflow=2,
            connect_args=connect_args,
        )
        self._sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        """A unit of work: commits on success, rolls back on any error.

        With `rollback_only`, every unit of work rolls back, so a preview reads but never writes.
        With `read_only`, PostgreSQL also refuses any write inside the transaction.
        """
        async with self._sessions() as session:
            transaction = await session.begin()
            if self.read_only:
                await session.execute(text("SET TRANSACTION READ ONLY"))
            try:
                yield session
            except BaseException:
                await transaction.rollback()
                raise
            if self.rollback_only:
                await transaction.rollback()
            else:
                await transaction.commit()

    async def ping(self) -> None:
        async with self.engine.connect() as connection:
            await connection.execute(text("SELECT 1"))

    async def revision(self) -> str | None:
        async with self.engine.connect() as connection:
            try:
                result = await connection.execute(text("SELECT version_num FROM alembic_version"))
            except Exception:
                return None
            row = result.first()
            return None if row is None else str(row[0])

    async def dispose(self) -> None:
        await self.engine.dispose()
