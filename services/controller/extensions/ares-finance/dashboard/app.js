const API_BASE = "http://127.0.0.1:3848";

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
        <div class="breakdown-val text-green">$${Number(data.breakdown.depository || 0).toLocaleString('en-US', { minimumFractionDigits: 2 })}</div>
      </div>
      <div class="breakdown-item">
        <div class="breakdown-label">Investments</div>
        <div class="breakdown-val text-blue">$${Number(data.breakdown.investment || 0).toLocaleString('en-US', { minimumFractionDigits: 2 })}</div>
      </div>
      <div class="breakdown-item">
        <div class="breakdown-label">Credit Balance</div>
        <div class="breakdown-val text-gold">$${Number(data.breakdown.credit || 0).toLocaleString('en-US', { minimumFractionDigits: 2 })}</div>
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
        <td><span class="badge badge-accent">Best Card Matched</span></td>
        <td class="${isPos ? 'amount-pos' : 'amount-neg'}">${amtFormatted}</td>
      `;
      tbody.appendChild(tr);
    });
    
    document.getElementById("txCountBadge").innerText = `${data.transactions.length} Recorded`;
  } catch (err) {
    console.error("Failed to load transactions", err);
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
