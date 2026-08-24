import os
import json
import uvicorn
from fastapi import FastAPI, Query, Body, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List, Dict, Any

from .engine.db import get_db, init_db, get_all_cards, save_card, delete_card
from .engine.card_optimizer import recommend_best_card, infer_category
from .engine.monarch_sync import MonarchSyncService

app = FastAPI(title="ARES Finance Sidecar", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

sync_service = MonarchSyncService()

@app.on_event("startup")
def startup_event():
    init_db()

@app.get("/health")
def health_check():
    return {
        "status": "ok",
        "service": "ares-finance",
        "version": "1.0.0",
        "loopback_only": True
    }

@app.get("/api/summary")
def get_financial_summary():
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT type, SUM(current_balance) as total FROM accounts GROUP BY type")
        balances_by_type = {row[0]: row[1] for row in cursor.fetchall()}
        
        cursor.execute("SELECT SUM(current_balance) FROM accounts WHERE type != 'credit'")
        assets = cursor.fetchone()[0] or 0.0
        
        cursor.execute("SELECT SUM(current_balance) FROM accounts WHERE type = 'credit'")
        liabilities = abs(cursor.fetchone()[0] or 0.0)
        
        net_worth = assets - liabilities
        
        cursor.execute("SELECT COUNT(*) FROM transactions")
        tx_count = cursor.fetchone()[0]
        
        return {
            "net_worth": round(net_worth, 2),
            "assets": round(assets, 2),
            "liabilities": round(liabilities, 2),
            "breakdown": balances_by_type,
            "total_transactions": tx_count
        }

@app.get("/api/accounts")
def get_accounts():
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, name, type, subtype, current_balance, updated_at FROM accounts ORDER BY current_balance DESC")
        accounts = [dict(row) for row in cursor.fetchall()]
        return {"accounts": accounts}

@app.get("/api/cards")
def get_cards_api():
    return {"cards": get_all_cards()}

class CardCreateRequest(BaseModel):
    id: str
    name: str
    issuer: str
    rewards: Dict[str, float]
    spend_cap_monthly: Optional[float] = 0.0
    quarterly_category: Optional[str] = ""
    notes: Optional[str] = ""

@app.post("/api/cards")
def create_or_update_card(req: CardCreateRequest):
    save_card(req.id, req.name, req.issuer, req.rewards, req.spend_cap_monthly or 0.0, req.quarterly_category or "", req.notes or "")
    return {"status": "saved", "card_id": req.id}

@app.delete("/api/cards/{card_id}")
def delete_card_api(card_id: str):
    success = delete_card(card_id)
    if not success:
        raise HTTPException(status_code=404, detail="Card not found")
    return {"status": "deleted", "card_id": card_id}

@app.get("/api/transactions")
def get_transactions(limit: int = 50, category: Optional[str] = None):
    with get_db() as conn:
        cursor = conn.cursor()
        if category:
            cursor.execute("SELECT * FROM transactions WHERE category = ? ORDER BY date DESC LIMIT ?", (category, limit))
        else:
            cursor.execute("SELECT * FROM transactions ORDER BY date DESC LIMIT ?", (limit,))
        transactions = [dict(row) for row in cursor.fetchall()]
        return {"transactions": transactions}

@app.get("/api/analytics/spending")
def get_spending_analytics():
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT category, SUM(ABS(amount)) as total_spent, COUNT(*) as tx_count
            FROM transactions
            WHERE amount < 0
            GROUP BY category
            ORDER BY total_spent DESC
        """)
        categories = [{"category": row[0], "total_spent": round(row[1], 2), "count": row[2]} for row in cursor.fetchall()]
        return {"spending_by_category": categories}

class CardRecommendRequest(BaseModel):
    merchant: str
    category: Optional[str] = None

@app.post("/api/recommend-card")
def recommend_card_api(req: CardRecommendRequest):
    return recommend_best_card(req.merchant, req.category)

class TokenSaveRequest(BaseModel):
    token: str

@app.post("/api/auth/monarch-token")
def save_monarch_token(req: TokenSaveRequest):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT OR REPLACE INTO auth_tokens (key, value) VALUES ('monarch_token', ?)", (req.token,))
        conn.commit()
    return {"status": "token_saved"}

@app.post("/api/sync")
async def trigger_sync():
    result = await sync_service.sync_now()
    return result

if __name__ == "__main__":
    port = int(os.getenv("FINANCE_PORT", 3848))
    uvicorn.run(app, host="127.0.0.1", port=port)
