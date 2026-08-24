const API_BASE = "http://127.0.0.1:3848";

// Tab Navigation
document.querySelectorAll(".nav-tab").forEach(tabBtn => {
  tabBtn.addEventListener("click", () => {
    document.querySelectorAll(".nav-tab").forEach(b => b.classList.remove("active"));
    document.querySelectorAll(".tab-content").forEach(c => c.classList.remove("active"));
    
    tabBtn.classList.add("active");
    const targetId = tabBtn.getAttribute("data-tab");
    document.getElementById(targetId).classList.add("active");
    
    if (targetId === "walletTab") loadWalletCards();
    if (targetId === "analyticsTab") loadAnalytics();
  });
});

async function fetchSummary() {
  try {
    const res = await fetch(`${API_BASE}/api/summary`);
    if (!res.ok) throw new Error("Sidecar offline");
    const data = await res.json();
    
    document.getElementById("netWorthDisplay").innerText = Number(data.net_worth).toLocaleString('en-US', { minimumFractionDigits: 2 });
    
    const breakdownContainer = document.getElementById("accountsBreakdown");
    breakdownContainer.innerHTML = `
      <div class="breakdown-item">
        <div class="breakdown-label">Liquid Assets</div>
        <div class="breakdown-val" style="color: var(--accent-green)">$${Number(data.breakdown.depository || 0).toLocaleString('en-US', { minimumFractionDigits: 2 })}</div>
      </div>
      <div class="breakdown-item">
        <div class="breakdown-label">Investments</div>
        <div class="breakdown-val" style="color: var(--accent-blue)">$${Number(data.breakdown.investment || 0).toLocaleString('en-US', { minimumFractionDigits: 2 })}</div>
      </div>
      <div class="breakdown-item">
        <div class="breakdown-label">Credit Balance</div>
        <div class="breakdown-val" style="color: var(--accent-gold)">$${Number(data.breakdown.credit || 0).toLocaleString('en-US', { minimumFractionDigits: 2 })}</div>
      </div>
    `;
    setOnlineStatus(true);
  } catch (err) {
    setOnlineStatus(false);
  }
}

async function fetchTransactions() {
  try {
    const res = await fetch(`${API_BASE}/api/transactions?limit=10`);
    if (!res.ok) return;
    const data = await res.json();
    
    const tbody = document.getElementById("txTableBody");
    tbody.innerHTML = "";
    
    data.transactions.forEach(tx => {
      const tr = document.createElement("tr");
      const isPos = tx.amount > 0;
      const amtFormatted = (isPos ? "+$" : "-$") + Math.abs(tx.amount).toFixed(2);
      
      tr.innerHTML = `
        <td>${tx.date}</td>
        <td><strong>${tx.merchant_name}</strong></td>
        <td><span class="tx-cat">${tx.category}</span></td>
        <td><span class="badge badge-accent">Best Multiplier Matched</span></td>
        <td class="${isPos ? 'amount-pos' : 'amount-neg'}">${amtFormatted}</td>
      `;
      tbody.appendChild(tr);
    });
    
    document.getElementById("txCountBadge").innerText = `${data.transactions.length} Recorded`;
  } catch (err) {
    console.error("Failed to load transactions", err);
  }
}

async function loadWalletCards() {
  try {
    const res = await fetch(`${API_BASE}/api/cards`);
    if (!res.ok) return;
    const data = await res.json();
    
    const container = document.getElementById("cardsGridContainer");
    container.innerHTML = "";
    
    data.cards.forEach(card => {
      const div = document.createElement("div");
      div.className = "wallet-card-item";
      
      const tags = Object.entries(card.rewards)
        .map(([cat, mult]) => `<span class="mult-tag">${cat}: ${mult}x</span>`)
        .join("");
        
      div.innerHTML = `
        <div>
          <div class="wallet-card-title">${card.name}</div>
          <div class="wallet-card-issuer">${card.issuer}</div>
          <div class="wallet-multipliers-tags">${tags}</div>
        </div>
        <div style="font-size: 11px; color: var(--text-secondary); margin-top: 8px;">
          ${card.notes || "Standard card terms."}
        </div>
      `;
      container.appendChild(div);
    });
  } catch (err) {
    console.error("Failed to load cards", err);
  }
}

async function loadAnalytics() {
  try {
    const res = await fetch(`${API_BASE}/api/analytics/spending`);
    if (!res.ok) return;
    const data = await res.json();
    
    const container = document.getElementById("analyticsBarsContainer");
    container.innerHTML = "";
    
    const maxSpent = Math.max(...data.spending_by_category.map(c => c.total_spent), 1);
    
    data.spending_by_category.forEach(cat => {
      const pct = Math.round((cat.total_spent / maxSpent) * 100);
      const row = document.createElement("div");
      row.className = "bar-row";
      row.innerHTML = `
        <div class="bar-label-row">
          <span><strong>${cat.category}</strong> (${cat.count} tx)</span>
          <span>$${cat.total_spent.toFixed(2)}</span>
        </div>
        <div class="bar-track">
          <div class="bar-fill" style="width: ${pct}%"></div>
        </div>
      `;
      container.appendChild(row);
    });
  } catch (err) {
    console.error("Failed to load analytics", err);
  }
}

async function evaluateCard() {
  const merchant = document.getElementById("merchantInput").value.trim();
  if (!merchant) return;
  
  try {
    const res = await fetch(`${API_BASE}/api/recommend-card`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ merchant })
    });
    const data = await res.json();
    
    if (data.recommended_card) {
      document.getElementById("recCardName").innerText = data.recommended_card.name;
      document.getElementById("recMultiplier").innerText = `${data.multiplier}x Multiplier (${data.detected_category.toUpperCase()})`;
      document.getElementById("recTip").innerText = data.tip;
    }
  } catch (err) {
    console.error("Optimization failed", err);
  }
}

function setOnlineStatus(online) {
  const badge = document.getElementById("sidecarStatus");
  if (online) {
    badge.innerHTML = `<span class="dot"></span> Sidecar Online`;
    badge.style.color = "var(--accent-green)";
  } else {
    badge.innerHTML = `<span class="dot" style="background: var(--danger)"></span> Offline (Using Local Cache)`;
    badge.style.color = "var(--danger)";
  }
}

// Modals
const authModal = document.getElementById("authModal");
document.getElementById("authModalBtn").addEventListener("click", () => authModal.classList.remove("hidden"));
document.getElementById("closeAuthModal").addEventListener("click", () => authModal.classList.add("hidden"));

document.getElementById("saveTokenBtn").addEventListener("click", async () => {
  const token = document.getElementById("monarchTokenInput").value.trim();
  if (!token) return;
  await fetch(`${API_BASE}/api/auth/monarch-token`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token })
  });
  authModal.classList.add("hidden");
  alert("Monarch token saved securely.");
});

const addCardModal = document.getElementById("addCardModal");
document.getElementById("addCardBtn").addEventListener("click", () => addCardModal.classList.remove("hidden"));
document.getElementById("closeAddCardModal").addEventListener("click", () => addCardModal.classList.add("hidden"));

document.getElementById("saveNewCardBtn").addEventListener("click", async () => {
  const name = document.getElementById("newCardName").value.trim();
  const issuer = document.getElementById("newCardIssuer").value.trim();
  let rewards = {};
  try {
    rewards = JSON.parse(document.getElementById("newCardRewards").value.trim() || '{"default": 1.0}');
  } catch (e) {
    rewards = { "default": 1.0 };
  }
  
  if (!name) return;
  const id = name.toLowerCase().replace(/[^a-z0-9]/g, "_");
  
  await fetch(`${API_BASE}/api/cards`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id, name, issuer, rewards })
  });
  
  addCardModal.classList.add("hidden");
  loadWalletCards();
});

document.getElementById("optimizeBtn").addEventListener("click", evaluateCard);
document.getElementById("merchantInput").addEventListener("keypress", (e) => {
  if (e.key === "Enter") evaluateCard();
});

document.getElementById("syncBtn").addEventListener("click", async () => {
  const btn = document.getElementById("syncBtn");
  btn.innerText = "Syncing...";
  try {
    await fetch(`${API_BASE}/api/sync`, { method: "POST" });
    await fetchSummary();
    await fetchTransactions();
  } finally {
    btn.innerHTML = `<span class="btn-icon">⚡</span> Sync Monarch`;
  }
});

fetchSummary();
fetchTransactions();
