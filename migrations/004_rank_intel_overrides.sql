CREATE TABLE IF NOT EXISTS rank_intel_overrides (
    id SERIAL PRIMARY KEY,
    projeto_id INTEGER NOT NULL REFERENCES projetos(id) ON DELETE CASCADE,
    keyword TEXT NOT NULL,
    action TEXT NOT NULL CHECK (action IN ('promote', 'block')),
    kw_type TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(projeto_id, keyword)
);
