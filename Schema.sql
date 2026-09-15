-- ============================================================
-- Smart Parking Management System - Database Schema
-- DSA Assignment - Multimedia University of Kenya
--
-- This file is just for reference/marking. The actual app
-- (app.py) creates these same tables automatically using
-- sqlite3 the first time it runs, so you don't need to run
-- this file separately.
-- ============================================================

-- Holds one row per physical parking slot. slot_id works like an
-- array index - we always know exactly which slot we're talking
-- about and can flip its status in O(1) with a single UPDATE.
CREATE TABLE IF NOT EXISTS parking_slots (
    slot_id INTEGER PRIMARY KEY,
    status  TEXT NOT NULL DEFAULT 'Available'   -- 'Available' or 'Occupied'
);

-- Logs every entry/exit event. A row with exit_time = NULL means
-- that vehicle is still parked (this is how we tell "active"
-- vehicles apart from ones that have already left).
CREATE TABLE IF NOT EXISTS transactions (
    transaction_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    reg_no          TEXT NOT NULL,
    slot_id         INTEGER NOT NULL,
    entry_time      TEXT NOT NULL,
    exit_time       TEXT,
    fee             INTEGER,
    payment_status  TEXT NOT NULL DEFAULT 'Pending',  -- 'Pending' or 'Paid'
    barrier_status  TEXT NOT NULL DEFAULT 'Closed',   -- 'Closed' or 'Open'
    FOREIGN KEY (slot_id) REFERENCES parking_slots(slot_id)
);