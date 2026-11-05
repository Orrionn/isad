from alembic import op
import sqlalchemy as sa

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # Создаём ENUM один раз; в create_table create_type=False, чтобы не дублировать
    analysis_status = sa.Enum(
        "queued", "processing", "completed", "failed",
        name="analysisstatus",
        create_type=False,
    )
    analysis_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "documents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("stored_path", sa.String(length=1000), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("content_type", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_documents_sha256", "documents", ["sha256"], unique=False)

    op.create_table(
        "analyses",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("document_id", sa.Integer(), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", analysis_status, nullable=False, server_default="queued"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("report", sa.JSON(), nullable=True),
        sa.Column("prompt_version", sa.String(length=50), nullable=False, server_default="v1"),
        sa.Column("model_name", sa.String(length=200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_analyses_document_id", "analyses", ["document_id"], unique=False)


def downgrade():
    op.drop_index("ix_analyses_document_id", table_name="analyses")
    op.drop_table("analyses")
    op.drop_index("ix_documents_sha256", table_name="documents")
    op.drop_table("documents")
    sa.Enum(name="analysisstatus").drop(op.get_bind(), checkfirst=True)