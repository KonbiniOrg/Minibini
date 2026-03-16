-- spread_timestamps.sql
-- Spreads out the timestamps of seed data so objects aren't all within
-- one second of each other.  Run AFTER seed_data.sh populates the database.
--
-- Usage:
--   mysql -u root minibini < scripts/spread_timestamps.sql
--
-- This script identifies jobs by their unique name, then updates timestamps
-- on the job and all related objects (worksheets, estimates, work orders,
-- tasks, bleps, invoices, history entries) to simulate realistic timing.
--
-- All times use business hours (roughly 8am-5pm) on weekdays.
-- "NOW" is treated as the current moment; everything is backdated from there.

-- =============================================
-- Helper: base reference point
-- =============================================
SET @now = NOW();

-- Shorthand for building timestamps: @now minus N days, plus H hours and M minutes
-- We'll write these inline as DATE_SUB(@now, INTERVAL X DAY) + INTERVAL Y HOUR + INTERVAL Z MINUTE


-- =============================================
-- SCENARIO 1: Meridian Architecture Group
-- "Custom reception desk with integrated lighting"
-- Status: approved, WO with tasks (not started), invoice draft
-- Timeline: ~3 weeks of pre-production work
-- =============================================

SET @j1 = (SELECT job_id FROM jobs WHERE name = 'Custom reception desk with integrated lighting');

-- Day 0: Job created (3 weeks ago, morning)
SET @j1_created = DATE_SUB(@now, INTERVAL 21 DAY) + INTERVAL 9 HOUR;
UPDATE jobs SET created_date = @j1_created WHERE job_id = @j1;

-- Day 1: Worksheet created (next morning, after reviewing notes)
SET @j1_ws_created = DATE_SUB(@now, INTERVAL 20 DAY) + INTERVAL 10 HOUR;
SET @j1_ws = (SELECT est_worksheet_id FROM worksheets WHERE job_id = @j1 LIMIT 1);
UPDATE worksheets SET created_date = @j1_ws_created WHERE est_worksheet_id = @j1_ws;

-- Day 3: Estimate generated from worksheet (afternoon, after pricing tasks)
SET @j1_est_created = DATE_SUB(@now, INTERVAL 18 DAY) + INTERVAL 14 HOUR;
SET @j1_est = (SELECT estimate_id FROM estimates WHERE job_id = @j1 LIMIT 1);
UPDATE estimates SET created_date = @j1_est_created WHERE estimate_id = @j1_est;

-- Day 4: Estimate sent to client (next morning)
SET @j1_est_sent = DATE_SUB(@now, INTERVAL 17 DAY) + INTERVAL 9 HOUR + INTERVAL 30 MINUTE;
SET @j1_est_expires = @j1_est_sent + INTERVAL 30 DAY;
UPDATE estimates SET sent_date = @j1_est_sent, expiration_date = @j1_est_expires
WHERE estimate_id = @j1_est;

-- Day 9: Client accepts estimate (5 days later, after internal review)
-- This also triggers job approval (start_date set by signal)
SET @j1_est_accepted = DATE_SUB(@now, INTERVAL 12 DAY) + INTERVAL 11 HOUR + INTERVAL 15 MINUTE;
UPDATE estimates SET closed_date = @j1_est_accepted WHERE estimate_id = @j1_est;
UPDATE jobs SET start_date = @j1_est_accepted WHERE job_id = @j1;

-- Day 10: Work order created (next morning)
SET @j1_wo_created = DATE_SUB(@now, INTERVAL 11 DAY) + INTERVAL 8 HOUR + INTERVAL 45 MINUTE;
-- WorkOrder has no timestamp fields, but we need it for task/blep reference
SET @j1_wo = (SELECT work_order_id FROM workorders WHERE job_id = @j1 LIMIT 1);

-- Day 10: Invoice created (same day, draft)
SET @j1_inv_created = DATE_SUB(@now, INTERVAL 11 DAY) + INTERVAL 15 HOUR;
SET @j1_inv = (SELECT invoice_id FROM invoices WHERE job_id = @j1 LIMIT 1);
UPDATE invoices SET created_date = @j1_inv_created WHERE invoice_id = @j1_inv;


-- =============================================
-- SCENARIO 2: Derek Lam — sign job, cancelled
-- "Custom exterior sign for coffee shop"
-- Timeline: Created 6 weeks ago, cancelled after 30+ days no deposit
-- =============================================

SET @j2 = (SELECT job_id FROM jobs WHERE name = 'Custom exterior sign for coffee shop');

-- Day 0: Job created (6 weeks ago)
SET @j2_created = DATE_SUB(@now, INTERVAL 42 DAY) + INTERVAL 13 HOUR + INTERVAL 30 MINUTE;
UPDATE jobs SET created_date = @j2_created WHERE job_id = @j2;

-- Day 1: Worksheet
SET @j2_ws_created = DATE_SUB(@now, INTERVAL 41 DAY) + INTERVAL 10 HOUR;
SET @j2_ws = (SELECT est_worksheet_id FROM worksheets WHERE job_id = @j2 LIMIT 1);
UPDATE worksheets SET created_date = @j2_ws_created WHERE est_worksheet_id = @j2_ws;

-- Day 3: Estimate generated
SET @j2_est_created = DATE_SUB(@now, INTERVAL 39 DAY) + INTERVAL 11 HOUR;
SET @j2_est = (SELECT estimate_id FROM estimates WHERE job_id = @j2 LIMIT 1);
UPDATE estimates SET created_date = @j2_est_created WHERE estimate_id = @j2_est;

-- Day 4: Estimate sent
SET @j2_est_sent = DATE_SUB(@now, INTERVAL 38 DAY) + INTERVAL 9 HOUR + INTERVAL 15 MINUTE;
SET @j2_est_expires = @j2_est_sent + INTERVAL 30 DAY;
UPDATE estimates SET sent_date = @j2_est_sent, expiration_date = @j2_est_expires
WHERE estimate_id = @j2_est;

-- Day 8: Client accepts (4 days after sent)
SET @j2_est_accepted = DATE_SUB(@now, INTERVAL 34 DAY) + INTERVAL 16 HOUR;
UPDATE estimates SET closed_date = @j2_est_accepted WHERE estimate_id = @j2_est;
UPDATE jobs SET start_date = @j2_est_accepted WHERE job_id = @j2;

-- Day 38: Cancelled (30 days later, no deposit)
SET @j2_cancelled = DATE_SUB(@now, INTERVAL 4 DAY) + INTERVAL 14 HOUR + INTERVAL 30 MINUTE;
UPDATE jobs SET completed_date = @j2_cancelled WHERE job_id = @j2;


-- =============================================
-- SCENARIO 3a: Bayside Brewing — completed cutting job
-- "Cut 3 aluminum sign blanks"
-- Timeline: Quick job, ~2 weeks total
-- =============================================

SET @j3 = (SELECT job_id FROM jobs WHERE name = 'Cut 3 aluminum sign blanks');

-- Day 0: Job created (5 weeks ago)
SET @j3_created = DATE_SUB(@now, INTERVAL 35 DAY) + INTERVAL 11 HOUR;
UPDATE jobs SET created_date = @j3_created WHERE job_id = @j3;

-- Day 1: Worksheet
SET @j3_ws_created = DATE_SUB(@now, INTERVAL 34 DAY) + INTERVAL 9 HOUR + INTERVAL 30 MINUTE;
SET @j3_ws = (SELECT est_worksheet_id FROM worksheets WHERE job_id = @j3 LIMIT 1);
UPDATE worksheets SET created_date = @j3_ws_created WHERE est_worksheet_id = @j3_ws;

-- Day 2: Estimate generated and sent same day (simple job)
SET @j3_est_created = DATE_SUB(@now, INTERVAL 33 DAY) + INTERVAL 10 HOUR;
SET @j3_est = (SELECT estimate_id FROM estimates WHERE job_id = @j3 LIMIT 1);
UPDATE estimates SET created_date = @j3_est_created WHERE estimate_id = @j3_est;

SET @j3_est_sent = DATE_SUB(@now, INTERVAL 33 DAY) + INTERVAL 14 HOUR;
SET @j3_est_expires = @j3_est_sent + INTERVAL 30 DAY;
UPDATE estimates SET sent_date = @j3_est_sent, expiration_date = @j3_est_expires
WHERE estimate_id = @j3_est;

-- Day 4: Accepted (quick turnaround, simple job)
SET @j3_est_accepted = DATE_SUB(@now, INTERVAL 31 DAY) + INTERVAL 10 HOUR + INTERVAL 45 MINUTE;
UPDATE estimates SET closed_date = @j3_est_accepted WHERE estimate_id = @j3_est;
UPDATE jobs SET start_date = @j3_est_accepted WHERE job_id = @j3;

-- Day 5: Work order, tasks started same day
SET @j3_wo = (SELECT work_order_id FROM workorders WHERE job_id = @j3 LIMIT 1);

-- Tasks completed over days 5-6 (quick cutting job)
-- Task 1 (CNC setup): Day 5, 8:30-10:00
SET @j3_t1_start = DATE_SUB(@now, INTERVAL 30 DAY) + INTERVAL 8 HOUR + INTERVAL 30 MINUTE;
SET @j3_t1_end   = DATE_SUB(@now, INTERVAL 30 DAY) + INTERVAL 10 HOUR;
-- Task 2 (Cut aluminum): Day 5, 10:15-11:00
SET @j3_t2_start = DATE_SUB(@now, INTERVAL 30 DAY) + INTERVAL 10 HOUR + INTERVAL 15 MINUTE;
SET @j3_t2_end   = DATE_SUB(@now, INTERVAL 30 DAY) + INTERVAL 11 HOUR;
-- Task 3 (Deburr): Day 5, 13:00-14:00
SET @j3_t3_start = DATE_SUB(@now, INTERVAL 30 DAY) + INTERVAL 13 HOUR;
SET @j3_t3_end   = DATE_SUB(@now, INTERVAL 30 DAY) + INTERVAL 14 HOUR;

-- Update bleps for j3 tasks (ordered by sort_order within the WO)
-- We need to match bleps by their task, and tasks by their work_order + sort order
UPDATE bleps b
JOIN tasks t ON b.task_id = t.task_id
SET b.start_time = @j3_t1_start, b.end_time = @j3_t1_end
WHERE t.work_order_id = @j3_wo AND t.sort_order = (
    SELECT MIN(sort_order) FROM tasks WHERE work_order_id = @j3_wo
);

UPDATE bleps b
JOIN tasks t ON b.task_id = t.task_id
SET b.start_time = @j3_t2_start, b.end_time = @j3_t2_end
WHERE t.work_order_id = @j3_wo AND t.sort_order = (
    SELECT sort_order FROM tasks WHERE work_order_id = @j3_wo ORDER BY sort_order LIMIT 1 OFFSET 1
);

UPDATE bleps b
JOIN tasks t ON b.task_id = t.task_id
SET b.start_time = @j3_t3_start, b.end_time = @j3_t3_end
WHERE t.work_order_id = @j3_wo AND t.sort_order = (
    SELECT MAX(sort_order) FROM tasks WHERE work_order_id = @j3_wo
);

-- Day 6: Invoice created
SET @j3_inv_created = DATE_SUB(@now, INTERVAL 29 DAY) + INTERVAL 9 HOUR;
SET @j3_inv = (SELECT invoice_id FROM invoices WHERE job_id = @j3 LIMIT 1);
UPDATE invoices SET created_date = @j3_inv_created WHERE invoice_id = @j3_inv;

-- Day 6: Job completed (afternoon)
SET @j3_completed = DATE_SUB(@now, INTERVAL 29 DAY) + INTERVAL 15 HOUR;
UPDATE jobs SET completed_date = @j3_completed WHERE job_id = @j3;


-- =============================================
-- SCENARIO 3b: Bayside Brewing — draft menu board
-- "Taproom menu board with changeable panels"
-- Timeline: Created 1 week ago, just a draft
-- =============================================

SET @j4 = (SELECT job_id FROM jobs WHERE name = 'Taproom menu board with changeable panels');

SET @j4_created = DATE_SUB(@now, INTERVAL 7 DAY) + INTERVAL 15 HOUR + INTERVAL 20 MINUTE;
UPDATE jobs SET created_date = @j4_created WHERE job_id = @j4;


-- =============================================
-- SCENARIO 4a: Cascade Event Rentals — draft with worksheet + estimate
-- "Storage rack system for rental inventory"
-- Timeline: Created 5 days ago
-- =============================================

SET @j5 = (SELECT job_id FROM jobs WHERE name = 'Storage rack system for rental inventory');

-- Day 0: Job created (5 days ago)
SET @j5_created = DATE_SUB(@now, INTERVAL 5 DAY) + INTERVAL 10 HOUR + INTERVAL 30 MINUTE;
UPDATE jobs SET created_date = @j5_created WHERE job_id = @j5;

-- Day 1: Worksheet
SET @j5_ws_created = DATE_SUB(@now, INTERVAL 4 DAY) + INTERVAL 9 HOUR;
SET @j5_ws = (SELECT est_worksheet_id FROM worksheets WHERE job_id = @j5 LIMIT 1);
UPDATE worksheets SET created_date = @j5_ws_created WHERE est_worksheet_id = @j5_ws;

-- Day 3: Estimate generated (still draft, not sent)
SET @j5_est_created = DATE_SUB(@now, INTERVAL 2 DAY) + INTERVAL 14 HOUR;
SET @j5_est = (SELECT estimate_id FROM estimates WHERE job_id = @j5 LIMIT 1);
UPDATE estimates SET created_date = @j5_est_created WHERE estimate_id = @j5_est;


-- =============================================
-- SCENARIO 4b: Cascade — submitted, estimate sent
-- "Portable bar units (set of 4)"
-- Timeline: Created 2 weeks ago
-- =============================================

SET @j6 = (SELECT job_id FROM jobs WHERE name = 'Portable bar units (set of 4)');

-- Day 0: Job created (2 weeks ago)
SET @j6_created = DATE_SUB(@now, INTERVAL 14 DAY) + INTERVAL 11 HOUR;
UPDATE jobs SET created_date = @j6_created WHERE job_id = @j6;

-- Day 1: Worksheet
SET @j6_ws_created = DATE_SUB(@now, INTERVAL 13 DAY) + INTERVAL 9 HOUR + INTERVAL 45 MINUTE;
SET @j6_ws = (SELECT est_worksheet_id FROM worksheets WHERE job_id = @j6 LIMIT 1);
UPDATE worksheets SET created_date = @j6_ws_created WHERE est_worksheet_id = @j6_ws;

-- Day 3: Estimate generated
SET @j6_est_created = DATE_SUB(@now, INTERVAL 11 DAY) + INTERVAL 13 HOUR;
SET @j6_est = (SELECT estimate_id FROM estimates WHERE job_id = @j6 LIMIT 1);
UPDATE estimates SET created_date = @j6_est_created WHERE estimate_id = @j6_est;

-- Day 4: Estimate sent, job submitted
SET @j6_est_sent = DATE_SUB(@now, INTERVAL 10 DAY) + INTERVAL 10 HOUR;
SET @j6_est_expires = @j6_est_sent + INTERVAL 30 DAY;
UPDATE estimates SET sent_date = @j6_est_sent, expiration_date = @j6_est_expires
WHERE estimate_id = @j6_est;


-- =============================================
-- SCENARIO 4c: Cascade — approved, in progress
-- "10 folding display easels"
-- Timeline: Created 3.5 weeks ago, 2 tasks done, 1 in progress
-- =============================================

SET @j7 = (SELECT job_id FROM jobs WHERE name = '10 folding display easels');

-- Day 0: Job created (25 days ago)
SET @j7_created = DATE_SUB(@now, INTERVAL 25 DAY) + INTERVAL 9 HOUR + INTERVAL 15 MINUTE;
UPDATE jobs SET created_date = @j7_created WHERE job_id = @j7;

-- Day 1: Worksheet
SET @j7_ws_created = DATE_SUB(@now, INTERVAL 24 DAY) + INTERVAL 10 HOUR;
SET @j7_ws = (SELECT est_worksheet_id FROM worksheets WHERE job_id = @j7 LIMIT 1);
UPDATE worksheets SET created_date = @j7_ws_created WHERE est_worksheet_id = @j7_ws;

-- Day 3: Estimate generated
SET @j7_est_created = DATE_SUB(@now, INTERVAL 22 DAY) + INTERVAL 11 HOUR + INTERVAL 30 MINUTE;
SET @j7_est = (SELECT estimate_id FROM estimates WHERE job_id = @j7 LIMIT 1);
UPDATE estimates SET created_date = @j7_est_created WHERE estimate_id = @j7_est;

-- Day 4: Estimate sent
SET @j7_est_sent = DATE_SUB(@now, INTERVAL 21 DAY) + INTERVAL 9 HOUR;
SET @j7_est_expires = @j7_est_sent + INTERVAL 30 DAY;
UPDATE estimates SET sent_date = @j7_est_sent, expiration_date = @j7_est_expires
WHERE estimate_id = @j7_est;

-- Day 8: Accepted
SET @j7_est_accepted = DATE_SUB(@now, INTERVAL 17 DAY) + INTERVAL 14 HOUR + INTERVAL 30 MINUTE;
UPDATE estimates SET closed_date = @j7_est_accepted WHERE estimate_id = @j7_est;
UPDATE jobs SET start_date = @j7_est_accepted WHERE job_id = @j7;

-- Day 9: Work order created
SET @j7_wo = (SELECT work_order_id FROM workorders WHERE job_id = @j7 LIMIT 1);

-- Task 1 (Design): Days 10-12, ~3 hours per day across 2.5 days
SET @j7_t1_start = DATE_SUB(@now, INTERVAL 15 DAY) + INTERVAL 9 HOUR;
SET @j7_t1_end   = DATE_SUB(@now, INTERVAL 13 DAY) + INTERVAL 12 HOUR;
-- Task 2 (Cut parts): Days 13-14
SET @j7_t2_start = DATE_SUB(@now, INTERVAL 12 DAY) + INTERVAL 8 HOUR + INTERVAL 30 MINUTE;
SET @j7_t2_end   = DATE_SUB(@now, INTERVAL 11 DAY) + INTERVAL 14 HOUR;
-- Task 3 (Shape and sand): Started day 15, still in progress
SET @j7_t3_start = DATE_SUB(@now, INTERVAL 10 DAY) + INTERVAL 9 HOUR;

-- Update bleps for completed tasks (task 1)
UPDATE bleps b
JOIN tasks t ON b.task_id = t.task_id
SET b.start_time = @j7_t1_start, b.end_time = @j7_t1_end
WHERE t.work_order_id = @j7_wo AND t.sort_order = (
    SELECT MIN(sort_order) FROM tasks WHERE work_order_id = @j7_wo
);

-- Task 2
UPDATE bleps b
JOIN tasks t ON b.task_id = t.task_id
SET b.start_time = @j7_t2_start, b.end_time = @j7_t2_end
WHERE t.work_order_id = @j7_wo AND t.sort_order = (
    SELECT sort_order FROM tasks WHERE work_order_id = @j7_wo ORDER BY sort_order LIMIT 1 OFFSET 1
);

-- Task 3 (in progress — blep has start_time but no end_time)
UPDATE bleps b
JOIN tasks t ON b.task_id = t.task_id
SET b.start_time = @j7_t3_start, b.end_time = NULL
WHERE t.work_order_id = @j7_wo AND t.sort_order = (
    SELECT sort_order FROM tasks WHERE work_order_id = @j7_wo ORDER BY sort_order LIMIT 1 OFFSET 2
);


-- =============================================
-- SCENARIO 5a: Pacific Crest — approved, WO ready, no invoice
-- "Hotel lobby accent wall panels"
-- Timeline: Created ~2.5 weeks ago
-- =============================================

SET @j8 = (SELECT job_id FROM jobs WHERE name = 'Hotel lobby accent wall panels');

-- Day 0: Job created (18 days ago)
SET @j8_created = DATE_SUB(@now, INTERVAL 18 DAY) + INTERVAL 10 HOUR + INTERVAL 30 MINUTE;
UPDATE jobs SET created_date = @j8_created WHERE job_id = @j8;

-- Day 0: Worksheet (same day, afternoon — Elena sent drawings already)
SET @j8_ws_created = DATE_SUB(@now, INTERVAL 18 DAY) + INTERVAL 14 HOUR;
SET @j8_ws = (SELECT est_worksheet_id FROM worksheets WHERE job_id = @j8 LIMIT 1);
UPDATE worksheets SET created_date = @j8_ws_created WHERE est_worksheet_id = @j8_ws;

-- Day 3: Estimate generated
SET @j8_est_created = DATE_SUB(@now, INTERVAL 15 DAY) + INTERVAL 11 HOUR;
SET @j8_est = (SELECT estimate_id FROM estimates WHERE job_id = @j8 LIMIT 1);
UPDATE estimates SET created_date = @j8_est_created WHERE estimate_id = @j8_est;

-- Day 4: Estimate sent
SET @j8_est_sent = DATE_SUB(@now, INTERVAL 14 DAY) + INTERVAL 9 HOUR + INTERVAL 30 MINUTE;
SET @j8_est_expires = @j8_est_sent + INTERVAL 30 DAY;
UPDATE estimates SET sent_date = @j8_est_sent, expiration_date = @j8_est_expires
WHERE estimate_id = @j8_est;

-- Day 7: Accepted
SET @j8_est_accepted = DATE_SUB(@now, INTERVAL 11 DAY) + INTERVAL 15 HOUR;
UPDATE estimates SET closed_date = @j8_est_accepted WHERE estimate_id = @j8_est;
UPDATE jobs SET start_date = @j8_est_accepted WHERE job_id = @j8;

-- Day 9: Work order created
SET @j8_wo = (SELECT work_order_id FROM workorders WHERE job_id = @j8 LIMIT 1);


-- =============================================
-- SCENARIO 5b: Pacific Crest — approved, deposit invoice sent
-- "Custom headboards for hotel renovation (12 units)"
-- Timeline: Created ~12 days ago
-- =============================================

SET @j9 = (SELECT job_id FROM jobs WHERE name = 'Custom headboards for hotel renovation (12 units)');

-- Day 0: Job created (12 days ago)
SET @j9_created = DATE_SUB(@now, INTERVAL 12 DAY) + INTERVAL 11 HOUR;
UPDATE jobs SET created_date = @j9_created WHERE job_id = @j9;

-- Day 1: Worksheet
SET @j9_ws_created = DATE_SUB(@now, INTERVAL 11 DAY) + INTERVAL 9 HOUR + INTERVAL 30 MINUTE;
SET @j9_ws = (SELECT est_worksheet_id FROM worksheets WHERE job_id = @j9 LIMIT 1);
UPDATE worksheets SET created_date = @j9_ws_created WHERE est_worksheet_id = @j9_ws;

-- Day 3: Estimate generated
SET @j9_est_created = DATE_SUB(@now, INTERVAL 9 DAY) + INTERVAL 13 HOUR;
SET @j9_est = (SELECT estimate_id FROM estimates WHERE job_id = @j9 LIMIT 1);
UPDATE estimates SET created_date = @j9_est_created WHERE estimate_id = @j9_est;

-- Day 4: Estimate sent
SET @j9_est_sent = DATE_SUB(@now, INTERVAL 8 DAY) + INTERVAL 10 HOUR;
SET @j9_est_expires = @j9_est_sent + INTERVAL 30 DAY;
UPDATE estimates SET sent_date = @j9_est_sent, expiration_date = @j9_est_expires
WHERE estimate_id = @j9_est;

-- Day 6: Accepted
SET @j9_est_accepted = DATE_SUB(@now, INTERVAL 6 DAY) + INTERVAL 11 HOUR + INTERVAL 45 MINUTE;
UPDATE estimates SET closed_date = @j9_est_accepted WHERE estimate_id = @j9_est;
UPDATE jobs SET start_date = @j9_est_accepted WHERE job_id = @j9;

-- Day 7: Work order created
SET @j9_wo = (SELECT work_order_id FROM workorders WHERE job_id = @j9 LIMIT 1);

-- Day 7: Deposit invoice created and sent (same day, afternoon)
SET @j9_inv_created = DATE_SUB(@now, INTERVAL 5 DAY) + INTERVAL 14 HOUR;
SET @j9_inv_sent = DATE_SUB(@now, INTERVAL 5 DAY) + INTERVAL 15 HOUR;
SET @j9_inv = (SELECT invoice_id FROM invoices WHERE job_id = @j9 LIMIT 1);
UPDATE invoices SET created_date = @j9_inv_created, sent_date = @j9_inv_sent
WHERE invoice_id = @j9_inv;


-- =============================================
-- SCENARIO 6: James Whitfield — rejected
-- "Backyard pergola with built-in planters"
-- Timeline: Created 4 weeks ago, rejected after ~10 days
-- =============================================

SET @j10 = (SELECT job_id FROM jobs WHERE name = 'Backyard pergola with built-in planters');

-- Day 0: Job created (28 days ago)
SET @j10_created = DATE_SUB(@now, INTERVAL 28 DAY) + INTERVAL 14 HOUR;
UPDATE jobs SET created_date = @j10_created WHERE job_id = @j10;

-- Day 2: Worksheet (took a day to think about scope)
SET @j10_ws_created = DATE_SUB(@now, INTERVAL 26 DAY) + INTERVAL 10 HOUR + INTERVAL 30 MINUTE;
SET @j10_ws = (SELECT est_worksheet_id FROM worksheets WHERE job_id = @j10 LIMIT 1);
UPDATE worksheets SET created_date = @j10_ws_created WHERE est_worksheet_id = @j10_ws;

-- Day 4: Estimate generated
SET @j10_est_created = DATE_SUB(@now, INTERVAL 24 DAY) + INTERVAL 15 HOUR;
SET @j10_est = (SELECT estimate_id FROM estimates WHERE job_id = @j10 LIMIT 1);
UPDATE estimates SET created_date = @j10_est_created WHERE estimate_id = @j10_est;

-- Day 5: Estimate sent
SET @j10_est_sent = DATE_SUB(@now, INTERVAL 23 DAY) + INTERVAL 9 HOUR + INTERVAL 15 MINUTE;
SET @j10_est_expires = @j10_est_sent + INTERVAL 30 DAY;
UPDATE estimates SET sent_date = @j10_est_sent, expiration_date = @j10_est_expires
WHERE estimate_id = @j10_est;

-- Day 10: Rejected (5 days after seeing the price)
SET @j10_rejected = DATE_SUB(@now, INTERVAL 18 DAY) + INTERVAL 16 HOUR + INTERVAL 30 MINUTE;
UPDATE estimates SET closed_date = @j10_rejected WHERE estimate_id = @j10_est;
-- Job has no start_date (never approved), no completed_date (rejected not cancelled)


-- =============================================
-- SCENARIO 7a: Aisha Okafor — WO complete, deposit paid
-- "Restaurant service counter with display case"
-- Timeline: Created 5 weeks ago, urgent project
-- =============================================

SET @j11 = (SELECT job_id FROM jobs WHERE name = 'Restaurant service counter with display case');

-- Day 0: Job created (35 days ago, urgent — same-day worksheet)
SET @j11_created = DATE_SUB(@now, INTERVAL 35 DAY) + INTERVAL 10 HOUR;
UPDATE jobs SET created_date = @j11_created WHERE job_id = @j11;

-- Day 0: Worksheet (same day, afternoon)
SET @j11_ws_created = DATE_SUB(@now, INTERVAL 35 DAY) + INTERVAL 15 HOUR;
SET @j11_ws = (SELECT est_worksheet_id FROM worksheets WHERE job_id = @j11 LIMIT 1);
UPDATE worksheets SET created_date = @j11_ws_created WHERE est_worksheet_id = @j11_ws;

-- Day 1: Estimate generated and sent (urgent, same day)
SET @j11_est_created = DATE_SUB(@now, INTERVAL 34 DAY) + INTERVAL 10 HOUR;
SET @j11_est = (SELECT estimate_id FROM estimates WHERE job_id = @j11 LIMIT 1);
UPDATE estimates SET created_date = @j11_est_created WHERE estimate_id = @j11_est;

SET @j11_est_sent = DATE_SUB(@now, INTERVAL 34 DAY) + INTERVAL 14 HOUR;
SET @j11_est_expires = @j11_est_sent + INTERVAL 30 DAY;
UPDATE estimates SET sent_date = @j11_est_sent, expiration_date = @j11_est_expires
WHERE estimate_id = @j11_est;

-- Day 3: Accepted (Aisha moves fast)
SET @j11_est_accepted = DATE_SUB(@now, INTERVAL 32 DAY) + INTERVAL 9 HOUR + INTERVAL 30 MINUTE;
UPDATE estimates SET closed_date = @j11_est_accepted WHERE estimate_id = @j11_est;
UPDATE jobs SET start_date = @j11_est_accepted WHERE job_id = @j11;

-- Day 4: Work order created
SET @j11_wo = (SELECT work_order_id FROM workorders WHERE job_id = @j11 LIMIT 1);

-- Day 4: Deposit invoice created, sent day 5, paid day 7
SET @j11_inv = (SELECT invoice_id FROM invoices WHERE job_id = @j11 LIMIT 1);
SET @j11_inv_created = DATE_SUB(@now, INTERVAL 31 DAY) + INTERVAL 11 HOUR;
SET @j11_inv_sent = DATE_SUB(@now, INTERVAL 30 DAY) + INTERVAL 9 HOUR;
SET @j11_inv_paid = DATE_SUB(@now, INTERVAL 28 DAY) + INTERVAL 14 HOUR;
UPDATE invoices SET created_date = @j11_inv_created, sent_date = @j11_inv_sent,
    closed_date = @j11_inv_paid
WHERE invoice_id = @j11_inv;

-- Tasks spread over days 5-18 (2 weeks of fabrication)
-- Task 1: Site measure (day 5, 2 hours)
-- Task 2: Design (days 6-8, spread across 3 days)
-- Task 3: Steel frame (days 9-12, heavy fabrication)
-- Task 4: Walnut top (days 12-14)
-- Task 5: Display case (days 14-16)
-- Task 6: Finish (days 16-17)
-- Task 7: Install (day 18)

SET @j11_task_times = 1; -- flag that we're setting these
UPDATE bleps b JOIN tasks t ON b.task_id = t.task_id
SET b.start_time = DATE_SUB(@now, INTERVAL 30 DAY) + INTERVAL 8 HOUR,
    b.end_time   = DATE_SUB(@now, INTERVAL 30 DAY) + INTERVAL 10 HOUR
WHERE t.work_order_id = @j11_wo AND t.sort_order = (
    SELECT MIN(sort_order) FROM tasks WHERE work_order_id = @j11_wo);

UPDATE bleps b JOIN tasks t ON b.task_id = t.task_id
SET b.start_time = DATE_SUB(@now, INTERVAL 29 DAY) + INTERVAL 9 HOUR,
    b.end_time   = DATE_SUB(@now, INTERVAL 27 DAY) + INTERVAL 16 HOUR
WHERE t.work_order_id = @j11_wo AND t.sort_order = (
    SELECT sort_order FROM tasks WHERE work_order_id = @j11_wo ORDER BY sort_order LIMIT 1 OFFSET 1);

UPDATE bleps b JOIN tasks t ON b.task_id = t.task_id
SET b.start_time = DATE_SUB(@now, INTERVAL 26 DAY) + INTERVAL 8 HOUR + INTERVAL 30 MINUTE,
    b.end_time   = DATE_SUB(@now, INTERVAL 23 DAY) + INTERVAL 15 HOUR
WHERE t.work_order_id = @j11_wo AND t.sort_order = (
    SELECT sort_order FROM tasks WHERE work_order_id = @j11_wo ORDER BY sort_order LIMIT 1 OFFSET 2);

UPDATE bleps b JOIN tasks t ON b.task_id = t.task_id
SET b.start_time = DATE_SUB(@now, INTERVAL 23 DAY) + INTERVAL 8 HOUR,
    b.end_time   = DATE_SUB(@now, INTERVAL 21 DAY) + INTERVAL 14 HOUR
WHERE t.work_order_id = @j11_wo AND t.sort_order = (
    SELECT sort_order FROM tasks WHERE work_order_id = @j11_wo ORDER BY sort_order LIMIT 1 OFFSET 3);

UPDATE bleps b JOIN tasks t ON b.task_id = t.task_id
SET b.start_time = DATE_SUB(@now, INTERVAL 21 DAY) + INTERVAL 9 HOUR,
    b.end_time   = DATE_SUB(@now, INTERVAL 19 DAY) + INTERVAL 16 HOUR
WHERE t.work_order_id = @j11_wo AND t.sort_order = (
    SELECT sort_order FROM tasks WHERE work_order_id = @j11_wo ORDER BY sort_order LIMIT 1 OFFSET 4);

UPDATE bleps b JOIN tasks t ON b.task_id = t.task_id
SET b.start_time = DATE_SUB(@now, INTERVAL 19 DAY) + INTERVAL 8 HOUR,
    b.end_time   = DATE_SUB(@now, INTERVAL 18 DAY) + INTERVAL 15 HOUR
WHERE t.work_order_id = @j11_wo AND t.sort_order = (
    SELECT sort_order FROM tasks WHERE work_order_id = @j11_wo ORDER BY sort_order LIMIT 1 OFFSET 5);

UPDATE bleps b JOIN tasks t ON b.task_id = t.task_id
SET b.start_time = DATE_SUB(@now, INTERVAL 17 DAY) + INTERVAL 8 HOUR,
    b.end_time   = DATE_SUB(@now, INTERVAL 17 DAY) + INTERVAL 16 HOUR
WHERE t.work_order_id = @j11_wo AND t.sort_order = (
    SELECT MAX(sort_order) FROM tasks WHERE work_order_id = @j11_wo);


-- =============================================
-- SCENARIO 7b: Aisha Okafor — completed
-- "Spice display shelving unit"
-- Timeline: Follow-up job, created 3 weeks ago, quick turnaround
-- =============================================

SET @j12 = (SELECT job_id FROM jobs WHERE name = 'Spice display shelving unit');

-- Day 0: Job created (22 days ago)
SET @j12_created = DATE_SUB(@now, INTERVAL 22 DAY) + INTERVAL 11 HOUR + INTERVAL 30 MINUTE;
UPDATE jobs SET created_date = @j12_created WHERE job_id = @j12;

-- Day 0: Worksheet (same day, easy follow-up)
SET @j12_ws_created = DATE_SUB(@now, INTERVAL 22 DAY) + INTERVAL 14 HOUR;
SET @j12_ws = (SELECT est_worksheet_id FROM worksheets WHERE job_id = @j12 LIMIT 1);
UPDATE worksheets SET created_date = @j12_ws_created WHERE est_worksheet_id = @j12_ws;

-- Day 1: Estimate generated and sent
SET @j12_est_created = DATE_SUB(@now, INTERVAL 21 DAY) + INTERVAL 10 HOUR;
SET @j12_est = (SELECT estimate_id FROM estimates WHERE job_id = @j12 LIMIT 1);
UPDATE estimates SET created_date = @j12_est_created WHERE estimate_id = @j12_est;

SET @j12_est_sent = DATE_SUB(@now, INTERVAL 21 DAY) + INTERVAL 15 HOUR;
SET @j12_est_expires = @j12_est_sent + INTERVAL 30 DAY;
UPDATE estimates SET sent_date = @j12_est_sent, expiration_date = @j12_est_expires
WHERE estimate_id = @j12_est;

-- Day 2: Accepted (next day, Aisha trusts us from previous job)
SET @j12_est_accepted = DATE_SUB(@now, INTERVAL 20 DAY) + INTERVAL 12 HOUR;
UPDATE estimates SET closed_date = @j12_est_accepted WHERE estimate_id = @j12_est;
UPDATE jobs SET start_date = @j12_est_accepted WHERE job_id = @j12;

-- Day 3: Work order
SET @j12_wo = (SELECT work_order_id FROM workorders WHERE job_id = @j12 LIMIT 1);

-- Tasks over days 3-7 (small job, ~5 days)
-- Task 1: Design (day 3, 2 hours)
UPDATE bleps b JOIN tasks t ON b.task_id = t.task_id
SET b.start_time = DATE_SUB(@now, INTERVAL 19 DAY) + INTERVAL 9 HOUR,
    b.end_time   = DATE_SUB(@now, INTERVAL 19 DAY) + INTERVAL 11 HOUR
WHERE t.work_order_id = @j12_wo AND t.sort_order = (
    SELECT MIN(sort_order) FROM tasks WHERE work_order_id = @j12_wo);

-- Task 2: Cut & shape walnut (day 4, 3 hours)
UPDATE bleps b JOIN tasks t ON b.task_id = t.task_id
SET b.start_time = DATE_SUB(@now, INTERVAL 18 DAY) + INTERVAL 8 HOUR + INTERVAL 30 MINUTE,
    b.end_time   = DATE_SUB(@now, INTERVAL 18 DAY) + INTERVAL 11 HOUR + INTERVAL 30 MINUTE
WHERE t.work_order_id = @j12_wo AND t.sort_order = (
    SELECT sort_order FROM tasks WHERE work_order_id = @j12_wo ORDER BY sort_order LIMIT 1 OFFSET 1);

-- Task 3: Weld brackets (day 4 afternoon, 2 hours)
UPDATE bleps b JOIN tasks t ON b.task_id = t.task_id
SET b.start_time = DATE_SUB(@now, INTERVAL 18 DAY) + INTERVAL 13 HOUR,
    b.end_time   = DATE_SUB(@now, INTERVAL 18 DAY) + INTERVAL 15 HOUR
WHERE t.work_order_id = @j12_wo AND t.sort_order = (
    SELECT sort_order FROM tasks WHERE work_order_id = @j12_wo ORDER BY sort_order LIMIT 1 OFFSET 2);

-- Task 4: Finish & LED (day 5, 3 hours)
UPDATE bleps b JOIN tasks t ON b.task_id = t.task_id
SET b.start_time = DATE_SUB(@now, INTERVAL 17 DAY) + INTERVAL 9 HOUR,
    b.end_time   = DATE_SUB(@now, INTERVAL 17 DAY) + INTERVAL 12 HOUR
WHERE t.work_order_id = @j12_wo AND t.sort_order = (
    SELECT sort_order FROM tasks WHERE work_order_id = @j12_wo ORDER BY sort_order LIMIT 1 OFFSET 3);

-- Task 5: Install (day 7, 2 hours)
UPDATE bleps b JOIN tasks t ON b.task_id = t.task_id
SET b.start_time = DATE_SUB(@now, INTERVAL 15 DAY) + INTERVAL 10 HOUR,
    b.end_time   = DATE_SUB(@now, INTERVAL 15 DAY) + INTERVAL 12 HOUR
WHERE t.work_order_id = @j12_wo AND t.sort_order = (
    SELECT MAX(sort_order) FROM tasks WHERE work_order_id = @j12_wo);

-- Day 7: Invoice created and sent
SET @j12_inv = (SELECT invoice_id FROM invoices WHERE job_id = @j12 LIMIT 1);
SET @j12_inv_created = DATE_SUB(@now, INTERVAL 15 DAY) + INTERVAL 14 HOUR;
SET @j12_inv_sent = DATE_SUB(@now, INTERVAL 15 DAY) + INTERVAL 15 HOUR;
UPDATE invoices SET created_date = @j12_inv_created, sent_date = @j12_inv_sent
WHERE invoice_id = @j12_inv;

-- Day 7: Job completed (afternoon, after install)
SET @j12_completed = DATE_SUB(@now, INTERVAL 15 DAY) + INTERVAL 16 HOUR;
UPDATE jobs SET completed_date = @j12_completed WHERE job_id = @j12;


-- =============================================
-- HISTORY TABLE: Spread history entry timestamps
-- to match the updated object timestamps
-- =============================================

-- Strategy: For each tracked object, shift its history entries proportionally.
-- The first entry gets the object's created_date, the last entry gets the
-- object's latest transition date (or created_date if only one entry).
-- Entries in between are linearly interpolated.

-- Jobs: spread history between created_date and latest meaningful date
-- We use a procedure-like approach with temporary tables for clarity.

-- For each job, update its history entries
-- First entry → created_date, subsequent entries spread to latest date

-- Helper: create a temp table mapping history entries to their new timestamps
DROP TEMPORARY TABLE IF EXISTS _hist_remap;
CREATE TEMPORARY TABLE _hist_remap (
    id INT PRIMARY KEY,
    new_ts DATETIME(6)
);

-- For jobs: spread history entries between created_date and COALESCE(completed_date, start_date, created_date)
INSERT INTO _hist_remap (id, new_ts)
SELECT
    h.id,
    TIMESTAMPADD(
        SECOND,
        TIMESTAMPDIFF(SECOND, j.created_date,
            COALESCE(j.completed_date, j.start_date, j.created_date)
        ) * (rn.row_num - 1) / GREATEST(rn.total - 1, 1),
        j.created_date
    ) + INTERVAL FLOOR(RAND() * 1800) SECOND  -- up to 30 min jitter
FROM history h
JOIN jobs j ON h.object_type = 'job' AND h.object_id = j.job_id
JOIN (
    SELECT
        id,
        object_id,
        ROW_NUMBER() OVER (PARTITION BY object_id ORDER BY timestamp) AS row_num,
        COUNT(*) OVER (PARTITION BY object_id) AS total
    FROM history
    WHERE object_type = 'job'
) rn ON rn.id = h.id;

-- For estimates
INSERT INTO _hist_remap (id, new_ts)
SELECT
    h.id,
    TIMESTAMPADD(
        SECOND,
        TIMESTAMPDIFF(SECOND, e.created_date,
            COALESCE(e.closed_date, e.sent_date, e.created_date)
        ) * (rn.row_num - 1) / GREATEST(rn.total - 1, 1),
        e.created_date
    ) + INTERVAL FLOOR(RAND() * 1800) SECOND
FROM history h
JOIN estimates e ON h.object_type = 'estimate' AND h.object_id = e.estimate_id
JOIN (
    SELECT
        id,
        object_id,
        ROW_NUMBER() OVER (PARTITION BY object_id ORDER BY timestamp) AS row_num,
        COUNT(*) OVER (PARTITION BY object_id) AS total
    FROM history
    WHERE object_type = 'estimate'
) rn ON rn.id = h.id;

-- For worksheets
INSERT INTO _hist_remap (id, new_ts)
SELECT
    h.id,
    TIMESTAMPADD(
        SECOND,
        TIMESTAMPDIFF(SECOND, w.created_date, w.created_date) * (rn.row_num - 1) / GREATEST(rn.total - 1, 1),
        w.created_date
    ) + INTERVAL (rn.row_num - 1) * 300 SECOND  -- 5 min between entries
    + INTERVAL FLOOR(RAND() * 120) SECOND
FROM history h
JOIN worksheets w ON h.object_type = 'estworksheet' AND h.object_id = w.est_worksheet_id
JOIN (
    SELECT
        id,
        object_id,
        ROW_NUMBER() OVER (PARTITION BY object_id ORDER BY timestamp) AS row_num,
        COUNT(*) OVER (PARTITION BY object_id) AS total
    FROM history
    WHERE object_type = 'estworksheet'
) rn ON rn.id = h.id;

-- For work orders (no timestamp fields, use parent job's start_date as base)
INSERT INTO _hist_remap (id, new_ts)
SELECT
    h.id,
    COALESCE(j.start_date, j.created_date)
        + INTERVAL (rn.row_num - 1) * 600 SECOND  -- 10 min between entries
        + INTERVAL FLOOR(RAND() * 300) SECOND
FROM history h
JOIN workorders wo ON h.object_type = 'workorder' AND h.object_id = wo.work_order_id
JOIN jobs j ON wo.job_id = j.job_id
JOIN (
    SELECT
        id,
        object_id,
        ROW_NUMBER() OVER (PARTITION BY object_id ORDER BY timestamp) AS row_num,
        COUNT(*) OVER (PARTITION BY object_id) AS total
    FROM history
    WHERE object_type = 'workorder'
) rn ON rn.id = h.id;

-- For invoices
INSERT INTO _hist_remap (id, new_ts)
SELECT
    h.id,
    TIMESTAMPADD(
        SECOND,
        TIMESTAMPDIFF(SECOND, i.created_date,
            COALESCE(i.closed_date, i.sent_date, i.created_date)
        ) * (rn.row_num - 1) / GREATEST(rn.total - 1, 1),
        i.created_date
    ) + INTERVAL FLOOR(RAND() * 900) SECOND
FROM history h
JOIN invoices i ON h.object_type = 'invoice' AND h.object_id = i.invoice_id
JOIN (
    SELECT
        id,
        object_id,
        ROW_NUMBER() OVER (PARTITION BY object_id ORDER BY timestamp) AS row_num,
        COUNT(*) OVER (PARTITION BY object_id) AS total
    FROM history
    WHERE object_type = 'invoice'
) rn ON rn.id = h.id;

-- For contacts (use a fixed base: 6 weeks ago, spread a few minutes apart)
INSERT INTO _hist_remap (id, new_ts)
SELECT
    h.id,
    DATE_SUB(@now, INTERVAL 42 DAY)
        + INTERVAL (h.object_id * 3600) SECOND  -- stagger by contact id
        + INTERVAL (rn.row_num - 1) * 180 SECOND
        + INTERVAL FLOOR(RAND() * 60) SECOND
FROM history h
JOIN (
    SELECT
        id,
        object_id,
        ROW_NUMBER() OVER (PARTITION BY object_id ORDER BY timestamp) AS row_num,
        COUNT(*) OVER (PARTITION BY object_id) AS total
    FROM history
    WHERE object_type = 'contact'
) rn ON rn.id = h.id
WHERE h.object_type = 'contact';

-- For businesses
INSERT INTO _hist_remap (id, new_ts)
SELECT
    h.id,
    DATE_SUB(@now, INTERVAL 42 DAY)
        + INTERVAL (h.object_id * 7200) SECOND
        + INTERVAL (rn.row_num - 1) * 180 SECOND
        + INTERVAL FLOOR(RAND() * 60) SECOND
FROM history h
JOIN (
    SELECT
        id,
        object_id,
        ROW_NUMBER() OVER (PARTITION BY object_id ORDER BY timestamp) AS row_num,
        COUNT(*) OVER (PARTITION BY object_id) AS total
    FROM history
    WHERE object_type = 'business'
) rn ON rn.id = h.id
WHERE h.object_type = 'business';

-- Apply all history timestamp remaps
UPDATE history h
JOIN _hist_remap r ON h.id = r.id
SET h.timestamp = r.new_ts;

DROP TEMPORARY TABLE _hist_remap;

-- =============================================
-- Done
-- =============================================
SELECT 'Timestamps spread successfully.' AS result;
