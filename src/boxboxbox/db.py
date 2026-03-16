from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


def get_engine(database_url: str):
    return create_async_engine(database_url, echo=False)


def get_session_factory(engine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)
