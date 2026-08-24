import json
from typing import Dict, Any, List
from .db import get_db

CATEGORY_KEYWORDS = {
    "dining": ["restaurant", "cafe", "coffee", "bistro", "starbucks", "mcdonald", "chipotle", "doordash", "uber eats", "grubhub", "blue bottle"],
    "gas": ["chevron", "shell", "exxon", "mobil", "76", "bp", "speedway", "costco gas"],
    "ev_charging": ["tesla supercharger", "evgo", "electrify america", "chargepoint", "blink"],
    "groceries": ["whole foods", "trader joe", "kroger", "safeway", "aldi", "sprouts", "heb", "publix"],
    "travel": ["united airlines", "delta", "american airlines", "marriott", "hilton", "airbnb", "uber", "lyft", "expedia"],
    "streaming": ["netflix", "spotify", "hulu", "disney", "apple music", "youtube premium", "hbo"]
}

def infer_category(merchant_name: str) -> str:
    merchant_lower = merchant_name.lower().strip()
    for cat, keywords in CATEGORY_KEYWORDS.items():
        if any(kw in merchant_lower for kw in keywords):
            return cat
    return "default"

def recommend_best_card(merchant_name: str, category_override: str = None) -> Dict[str, Any]:
    category = category_override if category_override else infer_category(merchant_name)
    
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, name, issuer, reward_structure, notes FROM cards")
        rows = cursor.fetchall()
        
        best_card = None
        max_multiplier = 0.0
        all_options = []
        
        for row in rows:
            card_id, name, issuer, reward_json, notes = row
            try:
                rewards = json.loads(reward_json)
            except Exception:
                rewards = {}
            
            # Check specific category, then normalized category, then default
            multiplier = rewards.get(category, rewards.get("default", 1.0))
            all_options.append({
                "card_id": card_id,
                "name": name,
                "issuer": issuer,
                "multiplier": multiplier,
                "notes": notes
            })
            
            if multiplier > max_multiplier:
                max_multiplier = multiplier
                best_card = {
                    "card_id": card_id,
                    "name": name,
                    "issuer": issuer,
                    "multiplier": multiplier,
                    "notes": notes
                }
        
        # Sort options descending by multiplier
        all_options.sort(key=lambda x: x["multiplier"], reverse=True)
        
        return {
            "merchant": merchant_name,
            "detected_category": category,
            "recommended_card": best_card,
            "multiplier": max_multiplier,
            "all_cards_ranking": all_options,
            "tip": f"Use {best_card['name']} for {max_multiplier}x rewards on {category} spend." if best_card else "Use standard catch-all card."
        }
