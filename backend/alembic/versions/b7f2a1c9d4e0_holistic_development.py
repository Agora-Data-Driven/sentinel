"""holistic development tables

Body metrics, personal records, career profile/achievements/goals, growth journal, and the
reading & philosophy canon. Additive only — no changes to existing tables.

Revision ID: b7f2a1c9d4e0
Revises: 2ea39b27b42d
Create Date: 2026-07-22 09:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'b7f2a1c9d4e0'
down_revision = '2ea39b27b42d'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'body_metrics',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('weight_kg', sa.Float(), nullable=True),
        sa.Column('body_fat_pct', sa.Float(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_body_metrics_user_id', 'body_metrics', ['user_id'])
    op.create_index('ix_body_metrics_date', 'body_metrics', ['date'])

    op.create_table(
        'personal_records',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('exercise_name', sa.String(length=120), nullable=False),
        sa.Column('weight_value', sa.Float(), nullable=False),
        sa.Column('weight_unit', sa.String(length=8), nullable=False),
        sa.Column('reps', sa.Integer(), nullable=False),
        sa.Column('achieved_on', sa.Date(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_personal_records_user_id', 'personal_records', ['user_id'])

    op.create_table(
        'development_profiles',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('headline', sa.String(length=200), nullable=True),
        sa.Column('resume_text', sa.Text(), nullable=True),
        sa.Column('resume_file_url', sa.String(length=500), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id'),
    )
    op.create_index('ix_development_profiles_user_id', 'development_profiles', ['user_id'])

    op.create_table(
        'career_achievements',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(length=200), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('achieved_on', sa.Date(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_career_achievements_user_id', 'career_achievements', ['user_id'])

    op.create_table(
        'professional_goals',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(length=200), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('target_date', sa.Date(), nullable=True),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('progress_pct', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_professional_goals_user_id', 'professional_goals', ['user_id'])

    op.create_table(
        'growth_items',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('kind', sa.String(length=16), nullable=False),
        sa.Column('title', sa.String(length=200), nullable=False),
        sa.Column('detail', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_growth_items_user_id', 'growth_items', ['user_id'])

    op.create_table(
        'reading_items',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(length=200), nullable=False),
        sa.Column('author', sa.String(length=160), nullable=True),
        sa.Column('kind', sa.String(length=16), nullable=False),
        sa.Column('url', sa.String(length=500), nullable=True),
        sa.Column('summary', sa.Text(), nullable=True),
        sa.Column('required', sa.Boolean(), nullable=False),
        sa.Column('sort_order', sa.Integer(), nullable=False),
        sa.Column('created_by', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['created_by'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table(
        'reading_progress',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('reading_item_id', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('reflection', sa.Text(), nullable=True),
        sa.Column('rating', sa.Integer(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.ForeignKeyConstraint(['reading_item_id'], ['reading_items.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'reading_item_id', name='uq_reading_progress_user_item'),
    )
    op.create_index('ix_reading_progress_user_id', 'reading_progress', ['user_id'])
    op.create_index('ix_reading_progress_reading_item_id', 'reading_progress', ['reading_item_id'])


def downgrade() -> None:
    op.drop_table('reading_progress')
    op.drop_table('reading_items')
    op.drop_table('growth_items')
    op.drop_table('professional_goals')
    op.drop_table('career_achievements')
    op.drop_table('development_profiles')
    op.drop_table('personal_records')
    op.drop_table('body_metrics')
