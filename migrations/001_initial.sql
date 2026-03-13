-- Herd AI — Initial Schema

CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    platform TEXT NOT NULL,
    platform_job_id TEXT NOT NULL,
    url TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    job_type TEXT NOT NULL,
    experience_level TEXT,
    budget_min REAL,
    budget_max REAL,
    hourly_rate_min REAL,
    hourly_rate_max REAL,
    required_skills TEXT,
    optional_skills TEXT,
    estimated_duration TEXT,
    client_name TEXT,
    client_country TEXT,
    client_rating REAL,
    client_total_spent REAL,
    client_hire_rate REAL,
    client_jobs_posted INTEGER,
    proposals_count INTEGER,
    interviewing_count INTEGER,
    posted_at TEXT NOT NULL,
    discovered_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'discovered',
    raw_data TEXT,
    UNIQUE(platform, platform_job_id)
);

CREATE TABLE IF NOT EXISTS scores (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES jobs(id),
    fast_score_total REAL,
    fast_score_breakdown TEXT,
    fast_score_pass INTEGER,
    deep_score_relevance REAL,
    deep_score_feasibility REAL,
    deep_score_profitability REAL,
    deep_score_win_probability REAL,
    deep_score_reasoning TEXT,
    deep_score_red_flags TEXT,
    final_score REAL,
    recommendation TEXT,
    scored_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS proposals (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES jobs(id),
    platform TEXT NOT NULL,
    platform_job_id TEXT NOT NULL,
    platform_proposal_id TEXT,
    bid_type TEXT NOT NULL,
    bid_amount REAL NOT NULL,
    cover_letter TEXT NOT NULL,
    questions_answers TEXT,
    confidence REAL,
    positioning_angle TEXT,
    experiment_variants TEXT,
    connects_cost REAL,
    status TEXT NOT NULL DEFAULT 'drafted',
    created_at TEXT NOT NULL,
    submitted_at TEXT,
    outcome_at TEXT,
    error TEXT
);

CREATE TABLE IF NOT EXISTS experiments (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    hypothesis TEXT NOT NULL,
    department TEXT NOT NULL,
    parameter TEXT NOT NULL,
    variants TEXT NOT NULL,
    primary_metric TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',
    created_at TEXT NOT NULL,
    started_at TEXT,
    ended_at TEXT
);

CREATE TABLE IF NOT EXISTS experiment_results (
    id TEXT PRIMARY KEY,
    experiment_id TEXT NOT NULL REFERENCES experiments(id),
    variant_key TEXT NOT NULL,
    sample_size INTEGER NOT NULL DEFAULT 0,
    metric_value REAL,
    confidence_low REAL,
    confidence_high REAL,
    is_significant INTEGER DEFAULT 0,
    p_value REAL,
    recorded_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS event_log (
    id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    source_department TEXT NOT NULL,
    payload TEXT NOT NULL,
    correlation_id TEXT,
    created_at TEXT NOT NULL
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_jobs_platform ON jobs(platform, platform_job_id);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_posted ON jobs(posted_at);
CREATE INDEX IF NOT EXISTS idx_scores_job ON scores(job_id);
CREATE INDEX IF NOT EXISTS idx_proposals_job ON proposals(job_id);
CREATE INDEX IF NOT EXISTS idx_proposals_status ON proposals(status);
CREATE INDEX IF NOT EXISTS idx_event_log_type ON event_log(event_type);
CREATE INDEX IF NOT EXISTS idx_event_log_correlation ON event_log(correlation_id);
