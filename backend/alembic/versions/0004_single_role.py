"""satu peran pengguna; status dikembalikan dihapus (migrasi data saja)

Revision ID: 0004
Revises: 0003
"""
from alembic import op

revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE users SET role='pengguna' WHERE role IN ('pengunggah','pemeriksa')")
    op.execute("UPDATE documents SET status='menunggu_cek' WHERE status='dikembalikan'")


def downgrade() -> None:
    raise NotImplementedError("migrasi data satu arah")
