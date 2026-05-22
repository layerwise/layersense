"""Initial persistence schema."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "project",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False, unique=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.Column("default_render_config_json", sa.Text(), nullable=False, server_default="{}"),
    )
    op.create_table(
        "scene",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column(
            "project_id",
            sa.Text(),
            sa.ForeignKey("project.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("order_index", sa.Integer(), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False, server_default=""),
        sa.Column("excalidraw_scene_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column(
            "current_render_id",
            sa.Text(),
            sa.ForeignKey("render.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("thumbnail_artifact_key", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.UniqueConstraint("project_id", "order_index"),
        sa.UniqueConstraint("project_id", "name"),
    )
    op.create_table(
        "frame",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column(
            "scene_id", sa.Text(), sa.ForeignKey("scene.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("order_index", sa.Integer(), nullable=False),
        sa.Column("excalidraw_frame_id", sa.Text(), nullable=False),
        sa.Column("prompt_augmentation", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.UniqueConstraint("scene_id", "order_index"),
        sa.UniqueConstraint("scene_id", "excalidraw_frame_id"),
    )
    op.create_table(
        "render",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column(
            "scene_id", sa.Text(), sa.ForeignKey("scene.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "parent_render_id",
            sa.Text(),
            sa.ForeignKey("render.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("refinement_prompt", sa.Text(), nullable=False, server_default=""),
        sa.Column("content_hash", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("scene_py_artifact_key", sa.Text(), nullable=True),
        sa.Column("preview_artifact_key", sa.Text(), nullable=True),
        sa.Column("final_artifact_key", sa.Text(), nullable=True),
        sa.Column("log_artifact_key", sa.Text(), nullable=True),
        sa.Column("cli_flags_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("conversation_id", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
    )
    op.create_index("ix_render_scene_id_created_at", "render", ["scene_id", "created_at"])
    op.create_index("ix_render_content_hash", "render", ["content_hash"])


def downgrade() -> None:
    op.drop_index("ix_render_content_hash", table_name="render")
    op.drop_index("ix_render_scene_id_created_at", table_name="render")
    op.drop_table("render")
    op.drop_table("frame")
    op.drop_table("scene")
    op.drop_table("project")
