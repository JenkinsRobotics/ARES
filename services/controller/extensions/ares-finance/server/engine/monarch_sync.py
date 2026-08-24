import os
import asyncio
import logging
from typing import Dict, Any, Optional
from .db import get_db

logger = logging.getLogger("ares.finance.sync")

class MonarchSyncService:
    def __init__(self):
        self.api_key = os.getenv("MONARCH_API_KEY", "")
        self.email = os.getenv("MONARCH_EMAIL", "")
        self.password = os.getenv("MONARCH_PASSWORD", "")
        self.last_sync_time = None
        self.is_syncing = False

    async def sync_now(self) -> Dict[str, Any]:
        if self.is_syncing:
            return {"status": "in_progress", "message": "Sync already running"}
            
        self.is_syncing = True
        try:
            # Check if monarch client library is available
            try:
                from monarchmoney import MonarchMoney
                client = MonarchMoney()
                
                # If credentials exist, perform real sync
                if self.api_key or (self.email and self.password):
                    if self.email and self.password:
                        await client.login(self.email, self.password)
                    accounts = await client.get_accounts()
                    transactions = await client.get_transactions(limit=100)
                    
                    with get_db() as conn:
                        cursor = conn.cursor()
                        # Update accounts
                        for acc in accounts.get("accounts", []):
                            cursor.execute("""
                                INSERT INTO accounts (id, name, type, subtype, current_balance, updated_at)
                                VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                                ON CONFLICT(id) DO UPDATE SET
                                    name=excluded.name,
                                    current_balance=excluded.current_balance,
                                    updated_at=CURRENT_TIMESTAMP
                            """, (acc["id"], acc["displayName"], acc["type"]["name"], acc.get("subtype", {}).get("name"), acc["currentBalance"]))
                        
                        # Update transactions
                        for tx in transactions.get("allTransactions", {}).get("results", []):
                            cursor.execute("""
                                INSERT INTO transactions (id, account_id, amount, date, merchant_name, category, notes, pending, updated_at)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                                ON CONFLICT(id) DO UPDATE SET
                                    amount=excluded.amount,
                                    merchant_name=excluded.merchant_name,
                                    category=excluded.category,
                                    updated_at=CURRENT_TIMESTAMP
                            """, (
                                tx["id"],
                                tx.get("account", {}).get("id"),
                                tx["amount"],
                                tx["date"],
                                tx.get("merchant", {}).get("name", "Unknown"),
                                tx.get("category", {}).get("name", "Uncategorized"),
                                tx.get("notes", ""),
                                1 if tx.get("pending") else 0
                            ))
                        conn.commit()
                        
                    return {
                        "status": "success",
                        "synced_accounts": len(accounts.get("accounts", [])),
                        "synced_transactions": len(transactions.get("allTransactions", {}).get("results", []))
                    }
            except ImportError:
                logger.info("monarchmoney package not installed; running in local SQLite demo mode.")
            except Exception as e:
                logger.warning(f"Monarch sync network call failed: {e}; keeping local offline data intact.")

            return {
                "status": "cached_offline",
                "message": "Loaded data from local SQLite database (Monarch API offline/cached mode)"
            }
        finally:
            self.is_syncing = False
