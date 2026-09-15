# Smart Parking Management System

Unit: Data Structures & Algorithms
Institution: Multimedia University of Kenya
Author: [HILLARY OMONDI OCHIENG] — [CIT-223-069/2025]
Tech Stack: Python, Streamlit, SQLite

A small web app that manages a parking lot: shows which slots are
free in real time, records a car when it enters, and works out the
fee (based on Kenyan pricing tiers) plus simulates a payment gate and
barrier when it leaves.

Live demo: [STREAMLIT COMMUNITY CLOUD LINK]

---

## 1. System Analysis & Module Breakdown

I broke the system into four core modules, each mapping to one
Python file section in `app.py`. I kept it as one file since the
project is small enough that splitting it into a package would just
add navigation overhead without any real benefit (this is the
"no over-engineering" principle — a 300-line student project doesn't
need microservices).

| Module | Responsibility | Key Functions |
|---|---|---|
| **Slot Display Module** | Shows a live grid of all slots, green (free) or red (occupied), and the running available-slot count. | `get_all_slots()`, `render_slot_grid()` |
| **Check-in / Entry Module** | Validates a registration number, finds the next free slot, stamps the entry time, writes the transaction. | `record_entry()`, `get_next_free_slot()` |
| **Billing & Exit Module** | Finds the active transaction for a car, computes how long it's been parked, applies the tiered pricing. | `get_bill_for_vehicle()`, `calculate_fee()` |
| **Transaction Log Module** | Shows the full entry/exit/payment history for every vehicle, oldest to newest. | `get_all_transactions()` |
| **Barrier Control Module** | Purely a visual gate — only ever shows "open" after `confirm_payment_and_exit()` has run. | `render_barrier()`, `confirm_payment_and_exit()` |
| **Database Module** | Owns the SQLite connection and table creation; every other module reads/writes through here rather than keeping its own separate state — one source of truth. | `get_connection()`, `init_db()` |

**Critical point on module coupling:** the availability count and the
slot grid colours are never stored as their own variable — they're
always computed live from the `parking_slots` table. This avoids a
classic bug where the displayed count and the actual DB state drift
apart because someone forgot to update a counter somewhere.

---

## 2. Algorithms & Data Structures

### 2.1 Slot Display Algorithm
1. Query all rows from `parking_slots`, ordered by `slot_id`.
2. Walk through the resulting list in chunks of `SLOTS_PER_ROW` to
   lay them out as a grid (`row_start` steps by 5, giving us 2D
   grid coordinates from a 1D list — the same trick used for
   mapping a 1D array onto a 2D board in games like tic-tac-toe).
3. Colour each box green/red based on its `status` field.
4. Recount `Available` rows for the summary line.

**Data structure:** the slot rows are pulled into a Python **list**
(`sqlite3.Row` objects). A list is the right fit here because slot
order matters (we always want Slot 1 to render before Slot 2) and we
need index-based chunking for the grid — both are O(1) list
operations.

### 2.2 Entry Algorithm
```
FUNCTION record_entry(reg_no):
    IF reg_no is blank: REJECT
    IF reg_no already in active_vehicles_map: REJECT (already parked)
    slot_id = lowest free slot_id (or NONE if lot is full)
    IF slot_id is NONE: REJECT (lot full)
    INSERT transaction row (reg_no, slot_id, entry_time = now)
    UPDATE parking_slots SET status = 'Occupied' WHERE slot_id = slot_id
    ACCEPT
```

**Data structure:** before checking whether a car is already parked,
we build a **hash map (Python dict)** of `{reg_no: transaction_row}`
from every transaction that hasn't exited yet. Looking up a
registration number in a dict is O(1) on average, versus O(n) if we
looped through a plain list of transactions checking each one. With
only a handful of cars this difference doesn't matter in practice,
but it's the textbook reason a hash map belongs here — the lookup
key (reg_no) is unique, so a dict is a natural fit.

### 2.3 Billing & Exit Algorithm
```
FUNCTION get_bill_for_vehicle(reg_no):
    row = active_vehicles_map[reg_no]      -- O(1) hash map lookup
    duration = now() - row.entry_time      -- datetime subtraction -> timedelta
    fee = calculate_fee(duration in minutes)
    RETURN bill details

FUNCTION calculate_fee(minutes):
    IF minutes <= 30:  return 0
    IF minutes <= 120: return 50
    IF minutes <= 240: return 100
    IF minutes <= 360: return 300
    ELSE:              return 500
```

**Data structure:** `datetime` objects for `entry_time`/`exit_time`,
and the `timedelta` produced by subtracting two datetimes. This is
the standard way to represent and manipulate time in Python, and it
lets us convert straight to minutes with `.total_seconds() / 60`
without any manual date-arithmetic.

The fee tiers themselves are a simple if/elif ladder rather than a
lookup table or binary search — with only 5 non-uniform ranges, a
ladder is the clearest and fastest to write; a lookup table would be
solving a problem we don't have.

### 2.4 Payment & Barrier Algorithm
```
FUNCTION confirm_payment_and_exit(transaction_id, slot_id, fee):
    SET transactions.exit_time = now()
    SET transactions.fee = fee
    SET transactions.payment_status = 'Paid'
    SET transactions.barrier_status = 'Open'      -- only after the above
    SET parking_slots.status = 'Available' WHERE slot_id = slot_id
```

The barrier is intentionally the *last* thing flipped, and only
inside this one function — there's no code path anywhere else that
sets `barrier_status = 'Open'`, which is what guarantees the barrier
can never open before payment is confirmed.

### 2.5 Why SQLite tables instead of just Python lists?
Streamlit re-runs the entire script top-to-bottom on every button
click. If slot/transaction state lived only in plain Python
variables, it would reset every time. SQLite gives us **persistent,
indexed storage** (the primary keys `slot_id` and `transaction_id`
behave like array indices but survive across reruns and even app
restarts) — which is why the database sits underneath the
dict/list structures rather than replacing them.

---

## 3. Database Design

```sql
-- One row per physical slot.
CREATE TABLE IF NOT EXISTS parking_slots (
    slot_id INTEGER PRIMARY KEY,
    status  TEXT NOT NULL DEFAULT 'Available'   -- 'Available' or 'Occupied'
);

-- One row per entry/exit event. exit_time IS NULL means the
-- vehicle is still parked.
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
```

Also provided separately as [`schema.sql`](./schema.sql) for easy
marking — `app.py` creates the same tables itself on first run, so
you don't need to run the SQL file manually.

---

## 4. Running the App

```bash
# 1. Create and activate a virtual environment (optional but recommended)
python -m venv venv
source venv/bin/activate        # on Windows: venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run the app
streamlit run app.py
```

The app opens in your browser at `http://localhost:8501`. A
`parking.db` SQLite file is created automatically in the project
folder the first time you run it.

---

## 5. Project Structure

```
smart-parking-system/
├── app.py               # Full Streamlit application (all 5 modules) — this is the graded submission
├── parking_demo.html    # Zero-install browser preview (HTML/CSS/JS only, no Python) — companion demo, not the graded artifact
├── schema.sql           # Reference copy of the database schema
├── requirements.txt     # Python dependencies
├── README.md            # This file
└── .gitignore           # Excludes parking.db and venv/ from version control
```

> **Note on `parking_demo.html`:** this is a static, in-browser
> re-implementation of the same logic (slot grid, entry, tiered
> billing, barrier) purely so anyone can preview the UI instantly by
> opening the file — it doesn't use Python or SQLite, and it is **not**
> the assignment submission. `app.py` is the actual Python/SQLite
> system being graded.

## 6. Pushing to GitHub (I added this for my own deep understanding of GitHub and it's commands)

```bash
# From inside the project folder:
git init
echo "parking.db" >> .gitignore
echo "venv/" >> .gitignore
echo "__pycache__/" >> .gitignore

git add .
git commit -m "Initial commit: Smart Parking Management System"

# Create an empty repo on GitHub first (via github.com), then:
git branch -M main
git remote add origin https://github.com/<your-username>/smart-parking-system.git
git push -u origin main
```

---

## 7. Possible Improvements (I did not implement it because it was out of scope)
- Real M-Pesa STK Push integration instead of a simulated "Confirm
  Payment" button.
- Multi-lot / multi-branch support.
- Admin login for viewing full transaction history and daily revenue.#   P A R K I N G - S Y S T E M - P R O J E C T  
 