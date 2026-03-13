-- Forward migration: add rate_range and urgency columns to bid_strategies.
-- Needed for installations that applied 002_bid_strategies.sql before these
-- columns were introduced. Fresh installs get them via 002 CREATE TABLE.

ALTER TABLE bid_strategies ADD COLUMN rate_floor REAL;
ALTER TABLE bid_strategies ADD COLUMN rate_ceil  REAL;
ALTER TABLE bid_strategies ADD COLUMN urgency    TEXT;
