from __future__ import annotations

from datetime import UTC, datetime
from typing import ClassVar

from sqlalchemy import ForeignKey, Index, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[str] = mapped_column(Text, default=utc_now_iso, nullable=False)
    updated_at: Mapped[str] = mapped_column(
        Text, default=utc_now_iso, onupdate=utc_now_iso, nullable=False
    )


class Project(TimestampMixin, Base):
    __tablename__ = "project"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    default_render_config_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")

    scenes: Mapped[list[Scene]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )


class Scene(TimestampMixin, Base):
    __tablename__ = "scene"
    __table_args__: ClassVar = (
        UniqueConstraint("project_id", "order_index"),
        UniqueConstraint("project_id", "name"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    project_id: Mapped[str] = mapped_column(
        Text, ForeignKey("project.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    order_index: Mapped[int] = mapped_column(nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False, default="")
    excalidraw_scene_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    current_render_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("render.id", ondelete="SET NULL"), nullable=True
    )
    thumbnail_artifact_key: Mapped[str | None] = mapped_column(Text, nullable=True)

    project: Mapped[Project] = relationship(back_populates="scenes")
    frames: Mapped[list[Frame]] = relationship(
        back_populates="scene", cascade="all, delete-orphan"
    )
    renders: Mapped[list[Render]] = relationship(
        back_populates="scene",
        cascade="all, delete-orphan",
        foreign_keys="Render.scene_id",
    )
    current_render: Mapped[Render | None] = relationship(
        foreign_keys=[current_render_id], post_update=True
    )


class Frame(TimestampMixin, Base):
    __tablename__ = "frame"
    __table_args__: ClassVar = (
        UniqueConstraint("scene_id", "order_index"),
        UniqueConstraint("scene_id", "excalidraw_frame_id"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    scene_id: Mapped[str] = mapped_column(
        Text, ForeignKey("scene.id", ondelete="CASCADE"), nullable=False
    )
    order_index: Mapped[int] = mapped_column(nullable=False)
    excalidraw_frame_id: Mapped[str] = mapped_column(Text, nullable=False)
    prompt_augmentation: Mapped[str] = mapped_column(Text, nullable=False, default="")

    scene: Mapped[Scene] = relationship(back_populates="frames")


class Render(TimestampMixin, Base):
    __tablename__ = "render"
    __table_args__: ClassVar = (
        Index("ix_render_scene_id_created_at", "scene_id", "created_at"),
        Index("ix_render_content_hash", "content_hash"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    scene_id: Mapped[str] = mapped_column(
        Text, ForeignKey("scene.id", ondelete="CASCADE"), nullable=False
    )
    parent_render_id: Mapped[str | None] = mapped_column(
        Text, ForeignKey("render.id", ondelete="SET NULL"), nullable=True
    )
    refinement_prompt: Mapped[str] = mapped_column(Text, nullable=False, default="")
    content_hash: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    scene_py_artifact_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    preview_artifact_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    final_artifact_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    log_artifact_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    cli_flags_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    conversation_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    scene: Mapped[Scene] = relationship(back_populates="renders", foreign_keys=[scene_id])
    parent_render: Mapped[Render | None] = relationship(remote_side=[id])
