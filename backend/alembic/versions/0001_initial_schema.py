"""initial schema

Revision ID: 0001_initial
Revises: 
Create Date: 2026-10-21 21:19:58.966149
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = '0001_initial'
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.create_table('sync_runs',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('kind', sa.String(length=32), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('games_updated', sa.Integer(), server_default='0', nullable=False),
    sa.Column('boxscores_synced', sa.Integer(), server_default='0', nullable=False),
    sa.Column('requests_made', sa.Integer(), server_default='0', nullable=False),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('details', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.CheckConstraint("status IN ('running','success','partial','failed')", name='ck_sync_runs_status'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_sync_runs_kind_started', 'sync_runs', ['kind', 'started_at'], unique=False)
    op.create_table('sync_state',
    sa.Column('key', sa.String(length=64), nullable=False),
    sa.Column('value', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('key')
    )
    op.create_table('teams',
    sa.Column('id', sa.Integer(), autoincrement=False, nullable=False),
    sa.Column('abbreviation', sa.String(length=8), nullable=False),
    sa.Column('display_name', sa.String(length=80), nullable=False),
    sa.Column('short_name', sa.String(length=40), nullable=False),
    sa.Column('location', sa.String(length=60), nullable=False),
    sa.Column('color', sa.String(length=8), nullable=True),
    sa.Column('alternate_color', sa.String(length=8), nullable=True),
    sa.Column('logo_url', sa.Text(), nullable=True),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('games',
    sa.Column('id', sa.BigInteger(), autoincrement=False, nullable=False),
    sa.Column('season', sa.SmallInteger(), nullable=False),
    sa.Column('season_type', sa.SmallInteger(), nullable=False),
    sa.Column('start_time', sa.DateTime(timezone=True), nullable=False),
    sa.Column('game_date', sa.Date(), nullable=False),
    sa.Column('home_team_id', sa.Integer(), nullable=False),
    sa.Column('away_team_id', sa.Integer(), nullable=False),
    sa.Column('home_score', sa.SmallInteger(), nullable=True),
    sa.Column('away_score', sa.SmallInteger(), nullable=True),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('status_detail', sa.String(length=80), nullable=True),
    sa.Column('venue_name', sa.String(length=120), nullable=True),
    sa.Column('venue_city', sa.String(length=80), nullable=True),
    sa.Column('venue_state', sa.String(length=40), nullable=True),
    sa.Column('neutral_site', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('boxscore_synced_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('boxscore_attempts', sa.SmallInteger(), server_default='0', nullable=False),
    sa.Column('boxscore_error', sa.Text(), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status IN ('scheduled','in_progress','final','postponed','canceled','suspended')", name='ck_games_status'),
    sa.CheckConstraint('home_team_id <> away_team_id', name='ck_games_distinct_teams'),
    sa.ForeignKeyConstraint(['away_team_id'], ['teams.id'], ),
    sa.ForeignKeyConstraint(['home_team_id'], ['teams.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_games_away_start', 'games', ['away_team_id', 'start_time'], unique=False)
    op.create_index('ix_games_game_date', 'games', ['game_date'], unique=False)
    op.create_index('ix_games_home_start', 'games', ['home_team_id', 'start_time'], unique=False)
    op.create_index('ix_games_missing_boxscore', 'games', ['start_time'], unique=False, postgresql_where=sa.text("status = 'final' AND boxscore_synced_at IS NULL"))
    op.create_index('ix_games_season_type', 'games', ['season', 'season_type'], unique=False)
    op.create_table('players',
    sa.Column('id', sa.Integer(), autoincrement=False, nullable=False),
    sa.Column('full_name', sa.String(length=120), nullable=False),
    sa.Column('first_name', sa.String(length=60), nullable=True),
    sa.Column('last_name', sa.String(length=60), nullable=True),
    sa.Column('search_name', sa.String(length=120), nullable=False),
    sa.Column('position', sa.String(length=8), nullable=True),
    sa.Column('jersey', sa.String(length=4), nullable=True),
    sa.Column('headshot_url', sa.Text(), nullable=True),
    sa.Column('height_in', sa.Float(), nullable=True),
    sa.Column('weight_lb', sa.Float(), nullable=True),
    sa.Column('birth_date', sa.Date(), nullable=True),
    sa.Column('current_team_id', sa.Integer(), nullable=True),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['current_team_id'], ['teams.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_players_current_team_id'), 'players', ['current_team_id'], unique=False)
    op.create_index('ix_players_search_name_trgm', 'players', ['search_name'], unique=False, postgresql_using='gin', postgresql_ops={'search_name': 'gin_trgm_ops'})
    op.create_table('player_game_stats',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('player_id', sa.Integer(), nullable=False),
    sa.Column('game_id', sa.BigInteger(), nullable=False),
    sa.Column('team_id', sa.Integer(), nullable=False),
    sa.Column('opponent_team_id', sa.Integer(), nullable=False),
    sa.Column('game_date', sa.Date(), nullable=False),
    sa.Column('season', sa.SmallInteger(), nullable=False),
    sa.Column('season_type', sa.SmallInteger(), nullable=False),
    sa.Column('is_home', sa.Boolean(), nullable=False),
    sa.Column('starter', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('did_not_play', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('dnp_reason', sa.String(length=80), nullable=True),
    sa.Column('minutes', sa.Float(), nullable=True),
    sa.Column('pts', sa.SmallInteger(), nullable=True),
    sa.Column('reb', sa.SmallInteger(), nullable=True),
    sa.Column('ast', sa.SmallInteger(), nullable=True),
    sa.Column('stl', sa.SmallInteger(), nullable=True),
    sa.Column('blk', sa.SmallInteger(), nullable=True),
    sa.Column('tov', sa.SmallInteger(), nullable=True),
    sa.Column('fgm', sa.SmallInteger(), nullable=True),
    sa.Column('fga', sa.SmallInteger(), nullable=True),
    sa.Column('fg3m', sa.SmallInteger(), nullable=True),
    sa.Column('fg3a', sa.SmallInteger(), nullable=True),
    sa.Column('ftm', sa.SmallInteger(), nullable=True),
    sa.Column('fta', sa.SmallInteger(), nullable=True),
    sa.Column('oreb', sa.SmallInteger(), nullable=True),
    sa.Column('dreb', sa.SmallInteger(), nullable=True),
    sa.Column('pf', sa.SmallInteger(), nullable=True),
    sa.Column('plus_minus', sa.SmallInteger(), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['game_id'], ['games.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['opponent_team_id'], ['teams.id'], ),
    sa.ForeignKeyConstraint(['player_id'], ['players.id'], ),
    sa.ForeignKeyConstraint(['team_id'], ['teams.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('player_id', 'game_id', name='uq_player_game_stats_player_game')
    )
    op.create_index('ix_pgs_game', 'player_game_stats', ['game_id'], unique=False)
    op.create_index('ix_pgs_player_date', 'player_game_stats', ['player_id', 'game_date'], unique=False)
    op.create_index('ix_pgs_player_opponent_date', 'player_game_stats', ['player_id', 'opponent_team_id', 'game_date'], unique=False)
    op.create_index('ix_pgs_season_date', 'player_game_stats', ['season', 'game_date'], unique=False)
    op.create_table('player_team_seasons',
    sa.Column('player_id', sa.Integer(), nullable=False),
    sa.Column('team_id', sa.Integer(), nullable=False),
    sa.Column('season', sa.SmallInteger(), nullable=False),
    sa.Column('games_played', sa.Integer(), nullable=False),
    sa.Column('first_game_date', sa.Date(), nullable=False),
    sa.Column('last_game_date', sa.Date(), nullable=False),
    sa.ForeignKeyConstraint(['player_id'], ['players.id'], ),
    sa.ForeignKeyConstraint(['team_id'], ['teams.id'], ),
    sa.PrimaryKeyConstraint('player_id', 'team_id', 'season')
    )


def downgrade() -> None:
    op.drop_table('player_team_seasons')
    op.drop_index('ix_pgs_season_date', table_name='player_game_stats')
    op.drop_index('ix_pgs_player_opponent_date', table_name='player_game_stats')
    op.drop_index('ix_pgs_player_date', table_name='player_game_stats')
    op.drop_index('ix_pgs_game', table_name='player_game_stats')
    op.drop_table('player_game_stats')
    op.drop_index('ix_players_search_name_trgm', table_name='players', postgresql_using='gin', postgresql_ops={'search_name': 'gin_trgm_ops'})
    op.drop_index(op.f('ix_players_current_team_id'), table_name='players')
    op.drop_table('players')
    op.drop_index('ix_games_season_type', table_name='games')
    op.drop_index('ix_games_missing_boxscore', table_name='games', postgresql_where=sa.text("status = 'final' AND boxscore_synced_at IS NULL"))
    op.drop_index('ix_games_home_start', table_name='games')
    op.drop_index('ix_games_game_date', table_name='games')
    op.drop_index('ix_games_away_start', table_name='games')
    op.drop_table('games')
    op.drop_table('teams')
    op.drop_table('sync_state')
    op.drop_index('ix_sync_runs_kind_started', table_name='sync_runs')
    op.drop_table('sync_runs')
