const API_BASE = "http://127.0.0.1:3849";

// Tab Switching Logic
document.querySelectorAll(".nav-tab").forEach(tabBtn => {
  tabBtn.addEventListener("click", () => {
    document.querySelectorAll(".nav-tab").forEach(b => b.classList.remove("active"));
    document.querySelectorAll(".tab-content").forEach(c => c.classList.remove("active"));
    
    tabBtn.classList.add("active");
    const targetId = tabBtn.getAttribute("data-tab");
    document.getElementById(targetId).classList.add("active");
  });
});

// Copy OBS Browser Source URL
document.getElementById("copyObsBtn").addEventListener("click", () => {
  navigator.clipboard.writeText("http://127.0.0.1:3849/overlay/avatar");
  const btn = document.getElementById("copyObsBtn");
  btn.innerText = "✅ URL Copied!";
  setTimeout(() => { btn.innerText = "📋 Copy OBS Overlay URL"; }, 2000);
});

// Avatar Viseme & Speech Test
let isSpeaking = false;
document.getElementById("testSpeechBtn").addEventListener("click", () => {
  if (isSpeaking) return;
  isSpeaking = true;
  const mouth = document.getElementById("avatarMouth");
  let count = 0;
  
  const interval = setInterval(() => {
    count++;
    const height = (count % 2 === 0) ? "16px" : "4px";
    const width = (count % 2 === 0) ? "20px" : "14px";
    mouth.style.height = height;
    mouth.style.width = width;
    
    if (count > 20) {
      clearInterval(interval);
      mouth.style.height = "6px";
      mouth.style.width = "14px";
      isSpeaking = false;
    }
  }, 100);
});

// Video Script Generator
document.getElementById("generateScriptBtn").addEventListener("click", async () => {
  const topic = document.getElementById("videoTopicInput").value.trim() || "Autonomous Agent Coding in 2026";
  const btn = document.getElementById("generateScriptBtn");
  btn.innerText = "Generating Script & Scenes...";
  
  try {
    const res = await fetch(`${API_BASE}/api/video/script`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ topic, duration_secs: 60 })
    });
    const data = await res.json();
    
    const container = document.getElementById("storyboardContainer");
    container.innerHTML = "";
    
    data.scenes.forEach(scene => {
      const div = document.createElement("div");
      div.className = "scene-card";
      div.innerHTML = `
        <div class="scene-title">Scene ${scene.scene_number} (${scene.timestamp_start} - ${scene.timestamp_end})</div>
        <div class="scene-voiceover">"${scene.voiceover_text}"</div>
        <div class="scene-prompt">🎬 Visual Prompt: ${scene.visual_prompt}</div>
      `;
      container.appendChild(div);
    });
    
    document.getElementById("renderSpecsBox").innerHTML = `
      <pre>${JSON.stringify(data.remotion_composition_spec, null, 2)}</pre>
    `;
  } catch (err) {
    console.error("Script generation failed", err);
  } finally {
    btn.innerText = "✨ Generate Script & Storyboard";
  }
});

// YouTube Ingestion
document.getElementById("learnYtBtn").addEventListener("click", async () => {
  const url = document.getElementById("ytUrlInput").value.trim();
  if (!url) return;
  
  const btn = document.getElementById("learnYtBtn");
  btn.innerText = "Ingesting Video...";
  
  try {
    const res = await fetch(`${API_BASE}/api/yt/learn`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url })
    });
    const data = await res.json();
    
    const resultsContainer = document.getElementById("learningResults");
    resultsContainer.innerHTML = `
      <h3 style="color: var(--accent-cyan); margin-bottom: 8px;">✅ Ingested: ${data.video_id} (${data.word_count} words)</h3>
      <p style="font-size: 13px; margin-bottom: 10px;">${data.summary}</p>
      <h4 style="font-size: 12px; color: var(--text-secondary);">Key Takeaways:</h4>
      <ul style="font-size: 12px; margin-left: 18px; color: var(--text-primary); margin-top: 6px;">
        ${data.key_takeaways.map(t => `<li>${t}</li>`).join("")}
      </ul>
    `;
    loadLibrary();
  } catch (err) {
    console.error("Ingestion failed", err);
  } finally {
    btn.innerText = "🧠 Ingest Video";
  }
});

async function loadLibrary() {
  try {
    const res = await fetch(`${API_BASE}/api/yt/knowledge`);
    if (!res.ok) return;
    const data = await res.json();
    
    const list = document.getElementById("knowledgeLibraryList");
    list.innerHTML = "";
    document.getElementById("libraryCount").innerText = `${data.library.length} Ingested`;
    
    data.library.forEach(item => {
      const div = document.createElement("div");
      div.className = "library-item";
      div.innerHTML = `
        <strong>${item.video_id}</strong> (${item.word_count} words)
        <div style="color: var(--text-secondary); font-size: 11px; margin-top: 2px;">${item.summary}</div>
      `;
      list.appendChild(div);
    });
  } catch (err) {
    console.error("Failed to load library", err);
  }
}

loadLibrary();
