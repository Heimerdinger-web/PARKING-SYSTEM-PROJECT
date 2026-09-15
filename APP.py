"""
Smart Parking Management System
--------------------------------
Data Structures & Algorithms Assignment
Multimedia University of Kenya

This is a single-file Streamlit app so it's easy to run and mark.
The idea: a small parking lot with a fixed number of slots. A car
comes in, we record it, when it leaves we work out how much it
owes based on how long it stayed, it "pays", and the barrier opens.

Data structures used (and why), quick summary before you dive in:
  - SQLite tables act as my persistent "arrays" of slot records and
    transaction records (rows = records, so we get indexed access by
    primary key, similar to array indexing but disk-backed).
  - A Python dict (hash map) is rebuilt each run to map
    reg_no -> active transaction, giving average O(1) lookup when I
    need to find a car that's currently parked (instead of scanning
    a list of transactions one by one, which would be O(n)).
  - A plain Python list is used to hold the slot rows in order so we
    can render them left-to-right, top-to-bottom in a grid (index
    position = grid position, so it's O(1) to place slot i on the
    grid).
  - datetime objects handle timestamps, and datetime subtraction
    gives us a timedelta we use for the fee calculation.
"""

import sqlite3
from datetime import datetime

import streamlit as st

# ---------------------------------------------------------------
# CONSTANTS
# ---------------------------------------------------------------
DB_NAME = "parking.db"
TOTAL_SLOTS = 10          # small number so the grid fits nicely on screen
SLOTS_PER_ROW = 5         # how many slot boxes per row in the grid

# ---------------------------------------------------------------
# DATABASE SETUP
# ---------------------------------------------------------------
def get_connection():
    """Opens a connection to our SQLite file. Kept as its own function
    so we don't repeat this line everywhere (DRY)."""
    conn = sqlite3.connect(DB_NAME, check_same_thread=False)
    conn.row_factory = sqlite3.Row  # lets us access columns by name, e.g. row["slot_id"]
    return conn


def init_db():
    """
    Creates the two tables the system needs if they don't exist yet,
    and seeds the parking_slots table with TOTAL_SLOTS empty slots the
    first time the app runs. This only runs its CREATE/INSERT logic
    once thanks to the IF NOT EXISTS / row-count checks below.
    """
    conn = get_connection()
    cur = conn.cursor()

    # parking_slots acts like our "array" of slots - one row per slot,
    # slot_id is essentially the array index.
    cur.execute("""
        CREATE TABLE IF NOT EXISTS parking_slots (
            slot_id INTEGER PRIMARY KEY,
            status TEXT NOT NULL DEFAULT 'Available'  -- 'Available' or 'Occupied'
        )
    """)

    # transactions is our log of every entry/exit event. entry_time is
    # always set, exit_time/fee/payment_status stay NULL/'Pending'
    # until the car leaves and pays.
    cur.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            transaction_id INTEGER PRIMARY KEY AUTOINCREMENT,
            reg_no TEXT NOT NULL,
            slot_id INTEGER NOT NULL,
            entry_time TEXT NOT NULL,
            exit_time TEXT,
            fee INTEGER,
            payment_status TEXT NOT NULL DEFAULT 'Pending',   -- 'Pending' or 'Paid'
            barrier_status TEXT NOT NULL DEFAULT 'Closed',    -- 'Closed' or 'Open'
            FOREIGN KEY (slot_id) REFERENCES parking_slots(slot_id)
        )
    """)

    # Seed the slots table only if it's empty (first run).
    cur.execute("SELECT COUNT(*) FROM parking_slots")
    if cur.fetchone()[0] == 0:
        for slot_id in range(1, TOTAL_SLOTS + 1):
            cur.execute(
                "INSERT INTO parking_slots (slot_id, status) VALUES (?, ?)",
                (slot_id, "Available"),
            )

    conn.commit()
    conn.close()


# ---------------------------------------------------------------
# MODULE 1: SLOT DISPLAY
# ---------------------------------------------------------------
def get_all_slots():
    """
    Returns all slot rows as a Python list (our in-memory 'array').
    We fetch them ordered by slot_id so the grid always renders in
    the same, predictable order.
    """
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT slot_id, status FROM parking_slots ORDER BY slot_id ASC")
    slots = cur.fetchall()  # list of sqlite3.Row objects
    conn.close()
    return slots


def get_available_count():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM parking_slots WHERE status = 'Available'")
    count = cur.fetchone()[0]
    conn.close()
    return count


def render_slot_grid():
    """
    Draws the parking grid: green box = Available, red box = Occupied.
    We loop over the slots list (an array) and use its index to decide
    which column of the Streamlit grid each box goes into - this is
    basically mapping a 1D array onto a 2D grid using integer division
    and modulo, a classic array-indexing trick.
    """
    slots = get_all_slots()
    st.subheader("🅿️ Live Slot Availability")

    for row_start in range(0, len(slots), SLOTS_PER_ROW):
        row_slots = slots[row_start:row_start + SLOTS_PER_ROW]
        cols = st.columns(len(row_slots))
        for col, slot in zip(cols, row_slots):
            colour = "#2ecc71" if slot["status"] == "Available" else "#e74c3c"  # green / red
            label = "FREE" if slot["status"] == "Available" else "FULL"
            col.markdown(
                f"""
                <div style="background-color:{colour}; padding:18px;
                border-radius:8px; text-align:center; color:white;
                font-weight:bold;">
                    Slot {slot['slot_id']}<br>{label}
                </div>
                """,
                unsafe_allow_html=True,
            )

    available = get_available_count()
    st.info(f"Available slots: {available} / {TOTAL_SLOTS}")


# ---------------------------------------------------------------
# MODULE 2: CHECK-IN / ENTRY
# ---------------------------------------------------------------
def get_next_free_slot():
    """
    Finds the lowest-numbered free slot. Conceptually this behaves
    like popping from a queue of free slots (first free slot in line
    gets used first) but we let SQL do the search with ORDER BY +
    LIMIT so we don't have to loop through Python lists ourselves.
    Returns None if the lot is full.
    """
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT slot_id FROM parking_slots WHERE status = 'Available' "
        "ORDER BY slot_id ASC LIMIT 1"
    )
    row = cur.fetchone()
    conn.close()
    return row["slot_id"] if row else None


def is_vehicle_already_parked(reg_no):
    """
    Uses our reg_no -> transaction hash map (built fresh from the DB)
    to check in O(1) average time whether this car is already inside,
    instead of scanning every transaction row one at a time.
    """
    active = build_active_vehicles_map()
    return reg_no.upper() in active


def build_active_vehicles_map():
    """
    Builds the hash map (Python dict) of currently-parked vehicles:
        { reg_no: transaction_row }
    A transaction counts as "active" if exit_time is still NULL.
    This is the key data structure for O(1) vehicle lookup, which is
    exactly why a dict/hash map is the right tool here instead of a
    list we'd have to search linearly.
    """
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM transactions WHERE exit_time IS NULL")
    rows = cur.fetchall()
    conn.close()

    active_map = {}
    for row in rows:
        active_map[row["reg_no"].upper()] = row
    return active_map


def record_entry(reg_no):
    """
    Step-by-step ENTRY algorithm:
      1. Reject blank registration numbers.
      2. Check the hash map - if this car is already parked, reject
         (can't double-park the same car).
      3. Find the next free slot (None means lot is full -> reject).
      4. Insert a new transaction row with entry_time = now().
      5. Flip that slot's status to 'Occupied'.
      6. Slot count updates automatically next time we query the DB,
         since availability is always derived live from the table
         rather than stored separately (single source of truth).
    """
    reg_no = reg_no.strip().upper()

    if not reg_no:
        return False, "Please type a vehicle registration number."

    if is_vehicle_already_parked(reg_no):
        return False, f"{reg_no} is already checked in and hasn't exited yet."

    slot_id = get_next_free_slot()
    if slot_id is None:
        return False, "Sorry, the parking lot is full. No slots available."

    entry_time = datetime.now().isoformat(timespec="seconds")

    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO transactions (reg_no, slot_id, entry_time, payment_status, barrier_status) "
        "VALUES (?, ?, ?, 'Pending', 'Closed')",
        (reg_no, slot_id, entry_time),
    )
    cur.execute(
        "UPDATE parking_slots SET status = 'Occupied' WHERE slot_id = ?",
        (slot_id,),
    )
    conn.commit()
    conn.close()

    return True, f"{reg_no} checked in at slot {slot_id}."


# ---------------------------------------------------------------
# MODULE 3: BILLING & EXIT
# ---------------------------------------------------------------
def calculate_fee(duration_minutes):
    """
    Applies the fixed Kenyan pricing tiers. Written as a simple
    if/elif ladder (not a fancy lookup table) since the ranges are
    non-uniform and there's only a handful of them - a lookup table
    would be over-engineering for 5 tiers.

        <= 30 min          : Ksh 0
        <= 2 hours (120min) : Ksh 50
        <= 4 hours (240min) : Ksh 100
        <= 6 hours (360min) : Ksh 300
        > 6 hours           : Ksh 500
    """
    if duration_minutes <= 30:
        return 0
    elif duration_minutes <= 120:
        return 50
    elif duration_minutes <= 240:
        return 100
    elif duration_minutes <= 360:
        return 300
    else:
        return 500


def get_bill_for_vehicle(reg_no):
    """
    Looks up the active transaction for this reg_no using our hash map
    (O(1) average), works out how long the car has been parked using
    a datetime subtraction (giving us a timedelta), then calculates
    the fee from that duration.
    """
    active_map = build_active_vehicles_map()
    reg_no = reg_no.strip().upper()

    if reg_no not in active_map:
        return None

    row = active_map[reg_no]
    entry_time = datetime.fromisoformat(row["entry_time"])
    now = datetime.now()
    duration = now - entry_time  # timedelta object
    duration_minutes = duration.total_seconds() / 60

    fee = calculate_fee(duration_minutes)

    return {
        "transaction_id": row["transaction_id"],
        "reg_no": reg_no,
        "slot_id": row["slot_id"],
        "entry_time": entry_time,
        "duration_minutes": round(duration_minutes, 1),
        "fee": fee,
    }


def confirm_payment_and_exit(transaction_id, slot_id, fee):
    """
    Step-by-step EXIT algorithm (runs once the user clicks "Confirm
    Payment"):
      1. Stamp exit_time on the transaction.
      2. Save the calculated fee.
      3. Mark payment_status as 'Paid'.
      4. Only NOW set barrier_status to 'Open' - the barrier is
         deliberately gated behind payment confirmation, per the
         requirement that it must never open before payment.
      5. Free up the slot back to 'Available', which is what makes
         the slot counter go back up automatically.
    """
    exit_time = datetime.now().isoformat(timespec="seconds")

    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "UPDATE transactions SET exit_time = ?, fee = ?, payment_status = 'Paid', "
        "barrier_status = 'Open' WHERE transaction_id = ?",
        (exit_time, fee, transaction_id),
    )
    cur.execute(
        "UPDATE parking_slots SET status = 'Available' WHERE slot_id = ?",
        (slot_id,),
    )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------
# MODULE 4: TRANSACTION LOG
# ---------------------------------------------------------------
def get_all_transactions():
    """
    Returns every transaction ever recorded, most recent first, so
    the lecturer/marker can see the full entry/exit/payment history
    in one place. This is a plain SELECT * - no fancy joins needed
    since transactions already stores slot_id directly.
    """
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM transactions ORDER BY transaction_id DESC")
    rows = cur.fetchall()
    conn.close()
    return rows


# ---------------------------------------------------------------
# MODULE 5: BARRIER CONTROL (visual simulation)
# ---------------------------------------------------------------
def render_barrier(is_open):
    """
    Just a visual indicator - a real barrier would be a motor/relay,
    but for this assignment we simulate it with an emoji + colour so
    markers can see the state change happen on payment.
    """
    if is_open:
        st.success("🟢 BARRIER OPEN — vehicle may exit")
    else:
        st.error("🔴 BARRIER CLOSED")


# ---------------------------------------------------------------
# STREAMLIT PAGE LAYOUT
# ---------------------------------------------------------------
def main():
    st.set_page_config(page_title="Smart Parking System", page_icon="🅿️", layout="wide")
    init_db()

    st.title("🅿️ Smart Parking Management System")
    st.caption("DSA Assignment — Multimedia University of Kenya")

    tab_display, tab_entry, tab_exit, tab_log = st.tabs(
        ["📊 Slot Display", "🚗 Vehicle Entry", "💳 Exit & Billing", "📜 Transaction Log"]
    )

    # ---- TAB 1: SLOT DISPLAY -----------------------------------
    with tab_display:
        render_slot_grid()

    # ---- TAB 2: ENTRY -------------------------------------------
    with tab_entry:
        st.subheader("Check In a Vehicle")
        reg_no_input = st.text_input("Vehicle Registration Number", placeholder="e.g. KDA 123A")

        if st.button("Check In", type="primary"):
            success, message = record_entry(reg_no_input)
            if success:
                st.success(message)
                st.balloons()
            else:
                st.warning(message)

    # ---- TAB 3: EXIT & BILLING -----------------------------------
    with tab_exit:
        st.subheader("Check Out a Vehicle")
        exit_reg_no = st.text_input("Enter Registration Number to Exit", key="exit_reg_no")

        # Use session_state to remember the bill between reruns so the
        # "Confirm Payment" button doesn't have to recalculate/lose it.
        if st.button("Calculate Fee"):
            bill = get_bill_for_vehicle(exit_reg_no)
            if bill is None:
                st.warning("No matching active vehicle found. Check the registration number.")
                st.session_state.pop("current_bill", None)
            else:
                st.session_state["current_bill"] = bill

        if "current_bill" in st.session_state:
            bill = st.session_state["current_bill"]
            st.write(f"**Vehicle:** {bill['reg_no']}")
            st.write(f"**Slot:** {bill['slot_id']}")
            st.write(f"**Entry Time:** {bill['entry_time'].strftime('%Y-%m-%d %H:%M:%S')}")
            st.write(f"**Duration Parked:** {bill['duration_minutes']} minutes")
            st.write(f"**Fee Due: Ksh {bill['fee']}**")

            render_barrier(is_open=False)

            if st.button("Confirm Payment & Open Barrier", type="primary"):
                confirm_payment_and_exit(
                    bill["transaction_id"], bill["slot_id"], bill["fee"]
                )
                st.session_state.pop("current_bill", None)
                render_barrier(is_open=True)
                st.success(f"Payment of Ksh {bill['fee']} confirmed. Slot {bill['slot_id']} is now free.")
                st.rerun()

    # ---- TAB 4: TRANSACTION LOG -----------------------------------
    with tab_log:
        st.subheader("Full Transaction Log")
        rows = get_all_transactions()
        if not rows:
            st.write("No transactions recorded yet.")
        else:
            # Convert sqlite3.Row objects into plain dicts so Streamlit
            # can render them as a table.
            table_data = [dict(row) for row in rows]
            st.dataframe(table_data, use_container_width=True)


if __name__ == "__main__":
    main()