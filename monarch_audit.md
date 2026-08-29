# ARES Finance: Monarch Money Integration Audit

## Overview
Your `ares finance` extension is a **Monarch Money integration** built into the ARES WebUI controller service. It provides a full-featured bridge between ARES and Monarch Money's Personal CFO platform.

---

## Code Audit

### Files Found
| File | Purpose | Lines |
|------|---------|-------|
| `services/controller/api/monarch.py` | Core MonarchClient wrapper + SQLite cache | 509 |
| `services/controller/api/monarch_routes.py` | WebUI API route handlers | ~200 |
| `services/controller/requirements.txt` | Dependency: `monarchmoney>=0.1.15` | - |

### Architecture

```
┌─────────────────┐     ┌──────────────────────┐     ┌──────────────────┐
│  ARES WebUI     │────▶│  monarch_routes.py   │────▶│  MonarchClient   │
│  (React/JS)     │     │  (HTTP endpoints)    │     │  (api/monarch.py)│
└─────────────────┘     └──────────────────────┘     └──────────────────┘
                                                        │
                                                        ▼
                                          ┌──────────────────────────┐
                                          │  monarchmoney (PyPI)     │
                                          │  - GraphQL API client    │
                                          │  - Session management    │
                                          └──────────────────────────┘
                                                        │
                                                        ▼
                                          ┌──────────────────────────┐
                                          │  Monarch Money Servers   │
                                          │  (api.monarch.com)       │
                                          └──────────────────────────┘
```

### Key Features Implemented

| Feature | Status | Notes |
|---------|--------|-------|
| **Session-based auth** | ✅ | Saves `.mm_session.pickle` for persistent login |
| **MFA support** | ✅ | Supports MFA secret key in login flow |
| **SQLite cache** | ✅ | Local cache for accounts, transactions, budgets, cashflow |
| **Offline fallback** | ✅ | Returns cached data when API fails |
| **Auto-reconnect** | ✅ | Attempts session restore on disconnect |
| **Accounts** | ✅ | `get_accounts()` with institution + balance data |
| **Transactions** | ✅ | `get_transactions(limit, offset)` with pagination |
| **Budgets** | ✅ | `get_budgets(month)` + `set_budget_amount()` |
| **Cashflow** | ✅ | `get_cashflow()` + summary |
| **Recurring** | ✅ | `get_recurring_transactions()` |
| **Holdings** | ✅ | `get_account_holdings()` for investments |
| **Create transaction** | ✅ | `create_transaction()` |
| **Update transaction** | ✅ | `update_transaction()` |
| **Account refresh** | ✅ | `request_refresh()` triggers Monarch sync |

---

## Comparison to Upstream (`monarchmoney` PyPI)

### Methods Your Code Uses vs. Available

| Method | Your Usage | Upstream Status |
|--------|------------|-----------------|
| `login()` | ✅ Used | ✅ Available |
| `interactive_login()` | ❌ Not used | ✅ Available (for CLI/Jupyter) |
| `save_session()` | ✅ Via login param | ✅ Available |
| `load_session()` | ✅ Via login param | ✅ Available |
| `get_accounts()` | ✅ | ✅ |
| `get_account_holdings()` | ✅ | ✅ |
| `get_budgets()` | ✅ | ✅ |
| `get_transactions()` | ✅ | ✅ |
| `get_cashflow()` | ✅ | ✅ |
| `get_cashflow_summary()` | ✅ | ✅ |
| `get_recurring_transactions()` | ✅ | ✅ |
| `set_budget_amount()` | ✅ | ✅ |
| `create_transaction()` | ✅ | ✅ |
| `update_transaction()` | ✅ | ✅ |
| `request_accounts_refresh_and_wait()` | ✅ | ✅ |
| `get_transaction_categories()` | ❌ Missing | ✅ Available |
| `get_transaction_category_groups()` | ❌ Missing | ✅ Available |
| `get_transaction_tags()` | ❌ Missing | ✅ Available |
| `get_institutions()` | ❌ Missing | ✅ Available |
| `get_account_history()` | ❌ Missing | ✅ Available |
| `delete_transaction()` | ❌ Missing | ✅ Available |
| `create_transaction_tag()` | ❌ Missing | ✅ Available |
| `set_transaction_tags()` | ❌ Missing | ✅ Available |
| `create_manual_account()` | ❌ Missing | ✅ Available |
| `delete_account()` | ❌ Missing | ✅ Available |
| `update_account()` | ❌ Missing | ✅ Available |

**Coverage: ~60%** — Core read/write ops are present; missing some metadata + admin ops.

---

## Comparison to Related Projects

### 1. `monarch-money-mcp` (colvint)
- **Purpose**: MCP server for Monarch Money
- **Built on**: `monarchmoney` library
- **Features**: Exposes Monarch as MCP tools for any MCP-compatible agent
- **Your advantage**: Direct WebUI integration with caching + offline mode

### 2. `monarch-mcp-server` (robcerda)
- **Purpose**: MCP server using `MonarchMoneyCommunity` fork
- **Features**: Full MFA support, GraphQL-based
- **Your advantage**: You have session persistence + local SQLite cache they don't mention

### 3. `monarchmoney-enhanced` (keithah)
- **Purpose**: Fork of `monarchmoney` with enhancements
- **Features**: Unknown (no README details)
- **Your advantage**: Your wrapper adds caching + auto-reconnect logic

### 4. `moneyflow` (wesm)
- **Purpose**: Personal finance data interface
- **Uses**: Derives from `monarchmoney`
- **Your advantage**: You're integrated into a live agent system with WebUI

---

## Setup Status

### ✅ Completed
- [x] Code written (`monarch.py`, `monarch_routes.py`)
- [x] Dependency added to `requirements.txt`
- [x] `monarchmoney==0.1.15` installed in venv

### ⏳ Pending
- [ ] Store Monarch credentials (email/password or MFA secret)
- [ ] Test connection via WebUI or API
- [ ] Verify data sync (accounts, transactions, budgets)
- [ ] Add missing methods if needed (categories, tags, institutions)

---

## Recommended Next Steps

### 1. Store Credentials
Monarch credentials should be stored securely. Options:
- **Option A**: Use ARES credential vault (`provider_credentials.py` or `secret_vault.py`)
- **Option B**: Environment variables (`MONARCH_EMAIL`, `MONARCH_PASSWORD`, `MONARCH_MFA_SECRET`)
- **Option C**: WebUI form → POST `/api/monarch/connect` → session saved to `.mm_session.pickle`

### 2. Test Connection
```bash
curl -X POST http://localhost:8000/api/monarch/connect \
  -H "Content-Type: application/json" \
  -d '{"email": "your@email.com", "password": "your-password"}'
```

### 3. Verify Data Flow
```bash
curl http://localhost:8000/api/monarch/accounts
curl http://localhost:8000/api/monarch/transactions?limit=10
curl http://localhost:8000/api/monarch/budgets
```

### 4. Optional Enhancements
- Add missing methods: `get_transaction_categories()`, `get_institutions()`, `delete_transaction()`
- Add WebUI Finance panel (if not already built)
- Add scheduled sync job (cron) to refresh accounts daily
- Add spending insights/analytics on top of cached data

---

## Security Notes

| Concern | Mitigation |
|---------|------------|
| Session file (`.mm_session.pickle`) | Stored in `~/.ares/` — ensure file permissions are 0600 |
| Credentials in transit | Use HTTPS for WebUI API calls |
| Credential storage | Use ARES secret vault, not plaintext config |
| Cache data | SQLite DB contains financial data — encrypt at rest if needed |

---

## Conclusion

Your ARES Finance extension is **well-architected** and covers the core Monarch Money use cases:
- ✅ Read accounts, transactions, budgets, cashflow
- ✅ Write transactions + budget adjustments
- ✅ Offline cache for resilience
- ✅ Auto-reconnect with session persistence

**Gaps vs. upstream**: Missing some metadata/admin methods (categories, tags, institutions, delete ops) — add these only if your use cases need them.

**Next action**: Store credentials and test the connection.
