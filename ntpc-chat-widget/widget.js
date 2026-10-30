(function () {
  const BACKEND_URL = "http://localhost:8000";

  const style = document.createElement("style");
  style.innerHTML = `
    @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600&display=swap');
    @keyframes ntpc-bounce {0%,80%,100%{transform:scale(0.7);opacity:0.5}40%{transform:scale(1);opacity:1}}
    @keyframes ntpc-slideUp {from{opacity:0;transform:translateY(20px)}to{opacity:1;transform:translateY(0)}}
    #ntpc-fab{position:fixed;bottom:28px;right:28px;z-index:999999;width:60px;height:60px;border-radius:50%;border:none;background:linear-gradient(135deg,#00A651,#007a3c);color:#fff;cursor:pointer;box-shadow:0 4px 20px rgba(0,166,81,0.4);font-size:26px;}
    #ntpc-window{position:fixed;bottom:24px;right:24px;z-index:999999;width:380px;height:580px;border-radius:20px;background:#fff;box-shadow:0 20px 60px rgba(0,0,0,0.18);display:none;flex-direction:column;font-family:'DM Sans',sans-serif;overflow:hidden;}
    #ntpc-header{background:linear-gradient(135deg,#00A651,#007a3c);padding:16px 18px;display:flex;align-items:center;justify-content:space-between;flex-shrink:0;}
    #ntpc-messages{flex:1;overflow-y:auto;padding:16px 14px;display:flex;flex-direction:column;gap:10px;}
    .ntpc-bot{max-width:82%;min-width:0;padding:10px 14px;border-radius:18px 18px 18px 4px;background:#f4f4f4;color:#222;font-size:13.5px;line-height:1.55;align-self:flex-start;overflow-wrap:anywhere;word-break:break-word;white-space:pre-wrap;}
    .ntpc-user{max-width:82%;min-width:0;padding:10px 14px;border-radius:18px 18px 4px 18px;background:linear-gradient(135deg,#00A651,#007a3c);color:#fff;font-size:13.5px;line-height:1.55;align-self:flex-end;overflow-wrap:anywhere;word-break:break-word;white-space:pre-wrap;}
    .ntpc-chip{background:#f9fdf9;border:1px solid #d4edda;border-radius:10px;padding:8px 12px;cursor:pointer;font-size:12.5px;color:#1a6636;text-align:left;font-family:'DM Sans',sans-serif;width:100%;display:block;margin-bottom:6px;}
    .ntpc-chip:hover{background:#e8f5ee;}
    #ntpc-input-area{padding:12px 14px;border-top:1px solid #f0f0f0;display:flex;gap:8px;align-items:flex-end;background:#fff;flex-shrink:0;}
    #ntpc-input{flex:1;resize:none;border:1.5px solid #e8e8e8;border-radius:12px;padding:10px 14px;font-size:13.5px;font-family:'DM Sans',sans-serif;background:#fafafa;color:#222;outline:none;}
    #ntpc-send{width:40px;height:40px;border-radius:50%;border:none;background:#00A651;color:#fff;cursor:pointer;font-size:16px;flex-shrink:0;}
    #ntpc-send:disabled{opacity:0.5;}
    .ntpc-typing{display:flex;gap:4px;align-items:center;padding:10px 14px;}
    .ntpc-typing span{width:7px;height:7px;border-radius:50%;background:#00A651;display:inline-block;animation:ntpc-bounce 1.2s infinite;}
    .ntpc-typing span:nth-child(2){animation-delay:0.2s;}
    .ntpc-typing span:nth-child(3){animation-delay:0.4s;}
  `;
  document.head.appendChild(style);

  const suggestions = [
    "What is NTPC's total installed capacity?",
    "Tell me about NTPC's renewable energy plans",
    "What are NTPC's sustainability initiatives?",
    "NTPC revenue in latest annual report",
  ];

  const fab = document.createElement("button");
  fab.id = "ntpc-fab";
  fab.innerHTML = "💬";
  fab.onclick = () => { win.style.display = "flex"; fab.style.display = "none"; };
  document.body.appendChild(fab);

  const win = document.createElement("div");
  win.id = "ntpc-window";
  win.innerHTML = `
    <div id="ntpc-header">
      <div style="display:flex;align-items:center;gap:10px">
        <div style="width:38px;height:38px;border-radius:50%;background:rgba(255,255,255,0.2);display:flex;align-items:center;justify-content:center;font-size:18px">⚡</div>
        <div>
          <div style="color:#fff;font-weight:600;font-size:15px">NTPC Assistant</div>
          <div style="color:rgba(255,255,255,0.75);font-size:11px">● Online · Powered by AI</div>
        </div>
      </div>
      <button onclick="document.getElementById('ntpc-window').style.display='none';document.getElementById('ntpc-fab').style.display='block'"
        style="background:rgba(255,255,255,0.15);border:none;border-radius:50%;width:32px;height:32px;cursor:pointer;color:#fff;font-size:16px;">✕</button>
    </div>
    <div id="ntpc-messages"></div>
    <div id="ntpc-input-area">
      <textarea id="ntpc-input" rows="1" placeholder="Ask anything about NTPC..."></textarea>
      <button id="ntpc-send" onclick="ntpcSend()">➤</button>
    </div>
  `;
  document.body.appendChild(win);

  document.getElementById("ntpc-input").addEventListener("keydown", function(e) {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); ntpcSend(); }
  });

  addBotMsg("Namaste! 🙏 I'm NTPC's AI Assistant. Ask me anything about NTPC!");
  
  const suggBox = document.createElement("div");
  suggBox.id = "ntpc-sugg";
  suggestions.forEach(q => {
    const btn = document.createElement("button");
    btn.className = "ntpc-chip";
    btn.textContent = q;
    btn.onclick = () => { suggBox.remove(); ntpcSend(q); };
    suggBox.appendChild(btn);
  });
  document.getElementById("ntpc-messages").appendChild(suggBox);

  function addBotMsg(text) {
    const msgs = document.getElementById("ntpc-messages");
    const d = document.createElement("div");
    d.className = "ntpc-bot";
    d.textContent = text;
    msgs.appendChild(d);
    msgs.scrollTop = msgs.scrollHeight;
  }

  function addUserMsg(text) {
    const msgs = document.getElementById("ntpc-messages");
    const d = document.createElement("div");
    d.className = "ntpc-user";
    d.textContent = text;
    msgs.appendChild(d);
    msgs.scrollTop = msgs.scrollHeight;
  }

  window.ntpcSend = async function(text) {
    const input = document.getElementById("ntpc-input");
    const q = text || input.value.trim();
    if (!q) return;
    input.value = "";
    const s = document.getElementById("ntpc-sugg");
    if (s) s.remove();
    addUserMsg(q);

    const msgs = document.getElementById("ntpc-messages");
    const typing = document.createElement("div");
    typing.id = "ntpc-typing";
    typing.className = "ntpc-bot ntpc-typing";
    typing.innerHTML = "<span></span><span></span><span></span>";
    msgs.appendChild(typing);
    msgs.scrollTop = msgs.scrollHeight;

    document.getElementById("ntpc-send").disabled = true;
    try {
      const res = await fetch(`${BACKEND_URL}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: q }),
      });
      const data = await res.json();
      document.getElementById("ntpc-typing").remove();
      addBotMsg(data.response || data.answer || "Sorry, couldn't find an answer.");
    } catch {
      document.getElementById("ntpc-typing").remove();
      addBotMsg("⚠️ Server se connect nahi ho pa raha.");
    } finally {
      document.getElementById("ntpc-send").disabled = false;
    }
  };
})();