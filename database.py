from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
import ssl

# Neon PostgreSQL (asyncpg driver)
# asyncpg needs ssl=True in connect_args, not sslmode in URL
DATABASE_URL = (
    "postgresql+asyncpg://neondb_owner:npg_GQY6B0PWEiDz"
    "@ep-floral-frog-ans6vdag-pooler.c-6.us-east-1.aws.neon.tech"
    "/neondb"
)

# Create SSL context for Neon
ssl_context = ssl.create_default_context()

engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    pool_pre_ping=True,
    connect_args={"ssl": ssl_context},
)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db():
    async with async_session() as session:
        yield session


async def init_db():
    async with engine.begin() as conn:
        from models import User, FriendRequest, Message  # noqa
        await conn.run_sync(Base.metadata.create_all)
