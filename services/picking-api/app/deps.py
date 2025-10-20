from collections.abc import AsyncGenerator
import os

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

DATABASE_URL = (
    "postgresql+asyncpg://"
    f"{os.getenv('PGUSER','postgres')}:{os.getenv('PGPASSWORD','postgres')}@"
    f"{os.getenv('PGHOST','db')}:{os.getenv('PGPORT','5432')}/"
    f"{os.getenv('PGDATABASE','picking')}"
)

engine = create_async_engine(DATABASE_URL, future=True, echo=False)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session
