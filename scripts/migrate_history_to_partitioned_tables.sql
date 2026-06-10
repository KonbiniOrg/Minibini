-- One-time data move: fan the old single `history` table out into the three
-- per-domain history tables (job_history / crm_history / purchasing_history).
--
-- Run AFTER applying migration 0020 (which creates the three tables) and while
-- the old `history` table still exists. Rows whose object_type is no longer
-- tracked (shift, shiftchangerequest, blepchangerequest, estworksheet) are
-- intentionally NOT copied — that history was dropped on purpose.
--
-- Idempotency: run once. Re-running duplicates rows. The new tables get fresh
-- auto-increment ids (history ids are not referenced by any FK); timestamps,
-- users, and payloads are preserved verbatim.

INSERT INTO job_history (entry_type, object_type, object_id, user_id, timestamp, changes, `text`)
SELECT entry_type, object_type, object_id, user_id, timestamp, changes, `text`
FROM history
WHERE object_type IN ('job', 'task', 'estimate', 'changeorder', 'change_order',
                      'invoice', 'material', 'deliverable', 'shipment');

INSERT INTO crm_history (entry_type, object_type, object_id, user_id, timestamp, changes, `text`)
SELECT entry_type, object_type, object_id, user_id, timestamp, changes, `text`
FROM history
WHERE object_type IN ('contact', 'business');

INSERT INTO purchasing_history (entry_type, object_type, object_id, user_id, timestamp, changes, `text`)
SELECT entry_type, object_type, object_id, user_id, timestamp, changes, `text`
FROM history
WHERE object_type IN ('purchaseorder', 'bill');

-- Sanity check (optional): rows that matched no domain and were therefore dropped.
-- SELECT object_type, COUNT(*) FROM history
-- WHERE object_type NOT IN ('job','task','estimate','changeorder','change_order',
--   'invoice','material','deliverable','shipment','contact','business',
--   'purchaseorder','bill')
-- GROUP BY object_type;

-- The old `history` table and its HistoryEntry model are left in place for now.
-- Once the move is verified, a follow-up migration removes the model (and drops
-- the table); do NOT `DROP TABLE history;` here while the model still exists.
