-- Herd AI — Bid Strategies

CREATE TABLE IF NOT EXISTS bid_strategies (
    id          TEXT PRIMARY KEY,
    job_id      TEXT NOT NULL REFERENCES jobs(id),
    decision    TEXT NOT NULL,          -- 'bid' | 'pass'
    bid_type    TEXT,                   -- 'hourly' | 'fixed'; NULL when decision='pass'
    bid_amount  REAL,                   -- NULL when decision='pass'
    rate_floor  REAL,                   -- NULL when decision='pass'
    rate_ceil   REAL,                   -- NULL when decision='pass'
    urgency     TEXT,                   -- 'immediate'|'normal'|'low'; NULL when decision='pass'
    positioning_angle TEXT,             -- NULL when decision='pass'
    confidence  REAL NOT NULL,
    reasoning   TEXT NOT NULL,
    pass_reason TEXT,                   -- only set when decision='pass'
    created_at  TEXT NOT NULL,
    UNIQUE (job_id)                     -- one strategy per job
);

CREATE INDEX IF NOT EXISTS idx_bid_strategies_job      ON bid_strategies(job_id);
CREATE INDEX IF NOT EXISTS idx_bid_strategies_decision ON bid_strategies(decision);
