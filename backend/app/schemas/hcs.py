from pydantic import BaseModel, Field


class HCSBreakdownOut(BaseModel):
    version: str
    analysis_window: str
    hcs: float = Field(description="Historical Consistency Score (descriptive index, not win probability)")
    h_weighted: float
    h_shrunk: float
    hits: int
    misses: int
    pushes: int
    qualifying_games: int
    effective_sample_size: float
    median: float | None
    iqr: float | None
    c_raw: float | None = None
    c_cushion: float
    m5_minutes: float | None
    m20_minutes: float | None
    m15_minutes: float | None = None
    m_modifier: float
    cushion_window: str = "L20"
    missing_data_flags: list[str] = []
    last_game_date: str | None = None
    component_historical: float
    component_cushion: float
    component_minutes: float
