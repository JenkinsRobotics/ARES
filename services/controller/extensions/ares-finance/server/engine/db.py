import sqlite3
import os
import json
from typing import List, Dict, Any, Optional

DB_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
DB_PATH = os.path.join(DB_DIR, "finance.db")

def get_db():
    os.makedirs(DB_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    os.makedirs(DB_DIR, exist_ok=True)
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS accounts (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                type TEXT NOT NULL,
                subtype TEXT,
                current_balance REAL NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                id TEXT PRIMARY KEY,
                account_id TEXT,
                amount REAL NOT NULL,
                date TEXT NOT NULL,
                merchant_name TEXT,
                category TEXT,
                notes TEXT,
                pending INTEGER DEFAULT 0,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (account_id) REFERENCES accounts(id)
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS cards (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                issuer TEXT NOT NULL,
                reward_structure TEXT NOT NULL,
                spend_cap_monthly REAL DEFAULT 0,
                quarterly_category TEXT,
                notes TEXT
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS auth_tokens (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        cursor.execute("SELECT COUNT(*) FROM cards")
        if cursor.fetchone()[0] == 0:
            default_cards = [
                ("csp", "Chase Sapphire Preferred", "Chase", json.dumps({"dining": 3.0, "travel": 2.0, "streaming": 3.0, "online_grocery": 3.0, "default": 1.0}), 0, "", "3x on dining, select streaming, online groceries"),
                ("citi_cc", "Citi Custom Cash", "Citi", json.dumps({"gas": 5.0, "groceries": 5.0, "dining": 5.0, "travel": 5.0, "ev_charging": 5.0, "default": 1.0}), 500.0, "", "5x on top eligible spend category up to $500/mo"),
                ("amex_gold", "Amex Gold", "American Express", json.dumps({"dining": 4.0, "groceries": 4.0, "flights": 3.0, "default": 1.0}), 25000.0, "", "4x on worldwide dining & US supermarkets up to $25k/yr"),
                ("venture_x", "Capital One Venture X", "Capital One", json.dumps({"travel_portal": 10.0, "flights_portal": 5.0, "default": 2.0}), 0, "", "2x miles catch-all on all purchases"),
                ("apple_card", "Apple Card", "Goldman Sachs", json.dumps({"apple_pay": 2.0, "apple_merchants": 3.0, "default": 1.0}), 0, "", "2% Daily Cash with Apple Pay, 3% at Apple/Nike/Uber")
            ]
            cursor.executemany("INSERT INTO cards (id, name, issuer, reward_structure, spend_cap_monthly, quarterly_category, notes) VALUES (?, ?, ?, ?, ?, ?, ?)", default_cards)
        
        cursor.execute("SELECT COUNT(*) FROM accounts")
        if cursor.fetchone()[0] == 0:
            sample_accounts = [
                ("acc_checking", "Primary Checking", "depository", "checking", 5420.50),
                ("acc_savings", "High Yield Savings (4.5%)", "depository", "savings", 28500.00),
                ("acc_roth", "Roth IRA Portfolio", "investment", "ira", 42100.80),
                ("acc_brokerage", "Taxable Brokerage", "investment", "brokerage", 65300.00),
                ("acc_credit", "Sapphire Preferred", "credit", "credit_card", -412.30)
            ]
            cursor.executemany("INSERT INTO accounts (id, name, type, subtype, current_balance) VALUES (?, ?, ?, ?, ?)", sample_accounts)
            
            sample_tx = [
                ("tx_01", "acc_credit", -45.50, "2026-08-22", "Whole Foods Market", "Groceries", "Organic groceries", 0),
                ("tx_02", "acc_credit", -12.40, "2026-08-22", "Blue Bottle Coffee", "Dining", "Espresso", 0),
                ("tx_03", "acc_checking", -120.00, "2026-08-21", "EVgo Charging Station", "EV / Gas", "Fast charging", 0),
                ("tx_04", "acc_checking", 3200.00, "2026-08-15", "Direct Deposit Payroll", "Income", "Salary", 0),
                ("tx_05", "acc_credit", -14.99, "2026-08-10", "Spotify Premium", "Streaming", "Subscription", 0)
            ]
            cursor.executemany("INSERT INTO transactions (id, account_id, amount, date, merchant_name, category, notes, pending) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", sample_tx)
        conn.commit()

def get_all_cards() -> List[Dict[str, Any]]:
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, name, issuer, reward_structure, spend_cap_monthly, quarterly_category, notes FROM cards")
        cards = []
        for row in cursor.fetchall():
            cards.append({
                "id": row["id"],
                "name": row["name"],
                "issuer": row["issuer"],
                "rewards": json.loads(row["reward_structure"]),
                "spend_cap_monthly": row["spend_cap_monthly"],
                "quarterly_category": row["quarterly_category"],
                "notes": row["notes"]
            })
        return cards

def save_card(card_id: str, name: str, issuer: str, rewards: Dict[str, float], spend_cap: float = 0, quarterly: str = "", notes: str = "") -> None:
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO cards (id, name, issuer, reward_structure, spend_cap_monthly, quarterly_category, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name=excluded.name,
                issuer=excluded.issuer,
                reward_structure=excluded.reward_structure,
                spend_cap_monthly=excluded.spend_cap_monthly,
                quarterly_category=excluded.quarterly_category,
                notes=excluded.notes
        """, (card_id, name, issuer, json.dumps(rewards), spend_cap, quarterly, notes))
        conn.commit()

def delete_card(card_id: str) -> bool:
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM cards WHERE id = ?", (card_id,))
        conn.commit()
        return cursor.rowcount > 0

init_db()
