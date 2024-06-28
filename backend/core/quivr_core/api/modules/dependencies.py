import os
from typing import AsyncGenerator, Callable, Generic, Type, TypeVar
from uuid import uuid4

from fastapi import Depends
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from quivr_core.api.models.settings import settings
from quivr_core.api.modules.user.entity.user_identity import UserIdentity


class BaseRepository:
    def __init__(self, session: AsyncSession):
        self.session = session


R = TypeVar("R", bound=BaseRepository)


class BaseService(Generic[R]):
    # associated repository type
    repository_cls: Type[R]

    def __init__(self, repository: R):
        self.repository = repository

    @classmethod
    def get_repository_cls(cls) -> Type[R]:
        return cls.repository_cls  # type: ignore


S = TypeVar("S", bound=BaseService)

# TODO: env variable debug sql_alchemy
async_engine = create_async_engine(
    settings.pg_database_async_url,
    echo=True if os.getenv("ORM_DEBUG") else False,
    future=True,
)


async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSession(async_engine) as session:
        yield session


def get_repository(repository_model: Type[R]) -> Callable[..., R]:
    def _get_repository(session: AsyncSession = Depends(get_async_session)) -> R:
        return repository_model(session)

    return _get_repository


def get_service(service: Type[S]) -> Callable[..., S]:
    def _get_service(
        repository: BaseRepository = Depends(
            get_repository(service.get_repository_cls())
        ),
    ) -> S:
        return service(repository)

    return _get_service


def get_current_user() -> UserIdentity:
    # TODO: get it one time from db
    return UserIdentity(
        id=uuid4(),
        email="admin@quivr.app",
    )
