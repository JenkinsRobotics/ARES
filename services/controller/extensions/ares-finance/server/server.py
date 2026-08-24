import os
import json
import uvicorn
from fastapi import FastAPI, Query, Body, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List, Dict, Any

from .engine.db import get_db, init_db
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

class CardRecommendRequest(BaseModel):
    merchant: str
    category: Optional[str] = None

@app.post("/api/recommend-card")
def recommend_card_api(req: CardRecommendRequest):
    return recommend_best_card(req.merchant, req.category)

@app.post("/api/sync")
async def trigger_sync():
    result = await sync_service.sync_now()
    return result

if __name__ == "__main__":
    port = int(os.getenv("FINANCE_PORT", 3848))
    uvicorn.run(app, host="127.0.0.1", port=port)
