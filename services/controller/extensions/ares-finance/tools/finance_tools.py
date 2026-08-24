from typing import Dict, Any, Optional
from ..server.engine.db import get_db
from ..server.engine.card_optimizer import recommend_best_card

def finance_summary() -> Dict[str, Any]:
    """Returns a snapshot of liquid assets, investments, liabilities, and net worth."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT type, SUM(current_balance) FROM accounts GROUP BY type")
        breakdown = {row[0]: row[1] for row in cursor.fetchall()}
        
        cursor.execute("SELECT SUM(current_balance) FROM accounts WHERE type != 'credit'")
        assets = cursor.fetchone()[0] or 0.0
        
        cursor.execute("SELECT SUM(current_balance) FROM accounts WHERE type = 'credit'")
        liabilities = abs(cursor.fetchone()[0] or 0.0)
        
        return {
            "net_worth": round(assets - liabilities, 2),
            "total_assets": round(assets, 2),
            "total_liabilities": round(liabilities, 2),
            "breakdown": breakdown
        }

def recommend_card(merchant: str, category: Optional[str] = None) -> Dict[str, Any]:
    """Evaluates the optimal credit card in your wallet for maximum points/cashback on a merchant purchase."""
    return recommend_best_card(merchant, category)

def search_transactions(query: Optional[str] = None, limit: int = 15) -> Dict[str, Any]:
    """Searches recent transaction ledger by merchant name or category."""
    with get_db() as conn:
        cursor = conn.cursor()
        if query:
            pattern = f"%{query}%"
            cursor.execute("""
                SELECT id, date, merchant_name, category, amount, notes 
                FROM transactions 
                WHERE merchant_name LIKE ? OR category LIKE ? 
                ORDER BY date DESC LIMIT ?
            """, (pattern, pattern, limit))
        else:
            cursor.execute("""
                SELECT id, date, merchant_name, category, amount, notes 
                FROM transactions 
                ORDER BY date DESC LIMIT ?
            """, (limit,))
        
        results = [dict(row) for row in cursor.fetchall()]
        return {"transactions": results, "count": len(results)}

def sync_monarch() -> Dict[str, Any]:
    """Triggers an offline/online sync against Monarch Money."""
    from ..server.engine.monarch_sync import MonarchSyncService
    import asyncio
    service = MonarchSyncService()
    return asyncio.run(service.sync_now())
