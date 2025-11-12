"""Add onupdate trigger to User.updated_at field

Revision ID: c7562c0a8dd5
Revises: cb8a1baee725
Create Date: 2025-10-02 00:00:50.179764

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c7562c0a8dd5'
down_revision: Union[str, Sequence[str], None] = 'cb8a1baee725'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema with database-specific logic."""
    # Add server-side onupdate trigger for User.updated_at
    # This ensures updated_at is automatically updated even for direct SQL updates

    # Detect database dialect
    bind = op.get_bind()
    dialect_name = bind.dialect.name

    if dialect_name == 'postgresql':
        # PostgreSQL: Use a trigger function
        op.execute("""
            CREATE OR REPLACE FUNCTION update_user_updated_at_column()
            RETURNS TRIGGER AS $$
            BEGIN
                NEW.updated_at = CURRENT_TIMESTAMP;
                RETURN NEW;
            END;
            $$ language 'plpgsql';
        """)

        op.execute("""
            CREATE TRIGGER update_user_updated_at
            BEFORE UPDATE ON users
            FOR EACH ROW
            EXECUTE FUNCTION update_user_updated_at_column();
        """)
    elif dialect_name == 'sqlite':
        # SQLite: Rely on SQLAlchemy's onupdate=func.now() at ORM level
        # Note: SQLite doesn't support server-side triggers for timestamp updates
        # The onupdate parameter in the model handles this at application level
        pass
    else:
        raise NotImplementedError(
            f"Database dialect '{dialect_name}' is not supported. "
            f"Supported dialects: postgresql, sqlite"
        )


def downgrade() -> None:
    """Downgrade schema with database-specific logic."""
    # Detect database dialect
    bind = op.get_bind()
    dialect_name = bind.dialect.name

    if dialect_name == 'postgresql':
        # Remove the trigger and function
        op.execute("DROP TRIGGER IF EXISTS update_user_updated_at ON users;")
        op.execute("DROP FUNCTION IF EXISTS update_user_updated_at_column();")
    elif dialect_name == 'sqlite':
        # No trigger to remove in SQLite
        pass
    # No error for other dialects on downgrade (allow cleanup)
