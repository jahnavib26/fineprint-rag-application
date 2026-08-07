from __future__ import annotations

from collections.abc import AsyncIterator
from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import get_settings


@lru_cache
def get_engine() -> AsyncEngine:
    url, connect_args = get_settings().database_connect_args()
    return create_async_engine(
        url,
        # Managed Postgres and PaaS proxies drop idle connections without
        # telling the pool, so the first query after a quiet period fails.
        pool_pre_ping=True,
        pool_recycle=300,
        connect_args=connect_args,
    )


@lru_cache
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency."""
    async with get_sessionmaker()() as session:
        yield session
