-- Each answer keeps how it ended, so a stopped or failed answer is saved and shown as such.
ALTER TABLE messages ADD COLUMN status text NOT NULL DEFAULT 'complete'
    CHECK (status IN ('complete', 'length', 'cancelled', 'failed'));
