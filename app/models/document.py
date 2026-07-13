from datetime import datetime

from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.models.schemas import FileStatus


class Base(DeclarativeBase):
    pass


class Document(Base):
    __tablename__ = "documents"
    id: Mapped[int] = mapped_column(primary_key=True)
    filename: Mapped[str] = mapped_column(unique=True)
    bucket: Mapped[str]
    object_key: Mapped[str]
    status: Mapped[FileStatus]
    size: Mapped[int]
    created_at: Mapped[datetime]
