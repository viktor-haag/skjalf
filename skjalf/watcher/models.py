"""SQLAlchemy persistence for folder registrations."""

from datetime import datetime

from sqlalchemy import create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, Session, sessionmaker

from ..config import DB_PATH


class Base(DeclarativeBase):
    pass


class FolderRegistration(Base):
    __tablename__ = "folder_registrations"

    id: Mapped[int] = mapped_column(primary_key=True)
    path: Mapped[str] = mapped_column(unique=True, index=True)
    added_at: Mapped[datetime] = mapped_column(default=datetime.utcnow)


def create_tables(engine):
    Base.metadata.create_all(engine)


class FolderStore:
    """Helper for managing folder registrations."""

    def __init__(self, db_url: str | None = None):
        self.engine = create_engine(db_url or DB_PATH, echo=False)
        create_tables(self.engine)
        self.Session = sessionmaker(self.engine, expire_on_commit=False)

    def add_folder(self, path: str) -> None:
        with Session(self.engine) as session:
            session.add(FolderRegistration(path=path))
            session.commit()

    def remove_folder(self, path: str) -> None:
        with Session(self.engine) as session:
            reg = session.execute(
                select(FolderRegistration).where(FolderRegistration.path == path)
            ).scalar_one_or_none()
            if reg:
                session.delete(reg)
                session.commit()

    def list_folders(self) -> list[str]:
        with Session(self.engine) as session:
            return list(session.execute(
                select(FolderRegistration.path)
            ).scalars())
