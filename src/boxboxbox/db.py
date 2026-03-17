from contextlib import AbstractAsyncContextManager
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


class SessionFactory(Protocol):
    """Callable that returns an async context manager yielding an AsyncSession."""

    def __call__(self) -> AbstractAsyncContextManager[AsyncSession]: ...


def get_engine(database_url: str):
    return create_async_engine(database_url, echo=False)


def get_session_factory(engine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)
