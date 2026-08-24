# ARES Financial Intelligence Extension

The `ares-finance` extension integrates personal financial data, Monarch Money sync, local SQLite storage, and a real-time credit card reward optimization engine into ARES and JaegerAI.

## Architecture

- **Sidecar Daemon:** Python FastAPI (port `3848`)
- **Data Engine:** Local encrypted SQLite database (`server/data/finance.db`)
- **Dashboard Tab:** `/finance` in ARES WebUI
- **Agent Tools:** `finance_summary`, `recommend_card`, `search_transactions`, `sync_monarch`

## Quickstart

```bash
cd services/controller/extensions/ares-finance
pip install -r requirements.txt
python -m server.server
```
