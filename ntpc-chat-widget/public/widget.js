(function () {
  const BACKEND_URL = "http://localhost:8000";

  const style = document.createElement("style");
  style.innerHTML = `
    #ntpc-fab {
      position: fixed;
      bottom: 28px;
      right: 28px;
      z-index: 999999;
      width: 60px;
      height: 60px;
      border-radius: 50%;
      border: none;
      background: #00A651;
      color: white;
      font-size: 26px;
      cursor: pointer;
      box-shadow: 0 4px 20px rgba(0,0,0,0.25);
    }

    #ntpc-window {
      position: fixed;
      bottom: 24px;
      right: 24px;
      width: 380px;
      height: 580px;
      background: white;
      z-index: 999999;
      border-radius: 18px;
      box-shadow: 0 20px 60px rgba(0,0,0,0.2);
      display: none;
      flex-direction: column;
      overflow: hidden;
      font-family: Arial, sans-serif;
    }

    #ntpc-header {
      background: #009944;
      color: white;
      padding: 16px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      font-weight: bold;
    }

    #ntpc-messages {
      flex: 1;
      padding: 14px;
      overflow-y: auto;
      display: flex;
      flex-direction: column;
      gap: 10px;
    }

    .ntpc-bot {
      background: #f1f1f1;
      color: #222;
      padding: 10px 14px;
      border-radius: 16px 16px 16px 4px;
      max-width: 82%;
      min-width: 0;
      align-self: flex-start;
      font-size: 14px;
      line-height: 1.4;
      overflow-wrap: anywhere;
      word-break: break-word;
      white-space: pre-wrap;
    }

    .ntpc-user {
      background: #00A651;
      color: white;
      padding: 10px 14px;
      border-radius: 16px 16px 4px 16px;
      max-width: 82%;
      min-width: 0;
      align-self: flex-end;
      font-size: 14px;
      line-height: 1.4;
      overflow-wrap: anywhere;
      word-break: break-word;
      white-space: pre-wrap;
    }

    #ntpc-input-area {
      display: flex;
      gap: 8px;
      padding: 12px;
      border-top: 1px solid #eee;
    }

    #ntpc-input {
      flex: 1;
      border: 1px solid #ddd;
      border-radius: 12px;
      padding: 10px;
      font-size: 14px;
      outline: none;
    }

    #ntpc-send {
      width: 42px;
      height: 42px;
      border-radius: 50%;
      border: none;
      background: #00A651;
      color: white;
      cursor: pointer;
      font-size: 18px;
    }
  `;
  document.head.appendChild(style);

  const fab = document.createElement("button");
  fab.id = "ntpc-fab";
  fab.innerHTML = "💬";
  document.body.appendChild(fab);

  const win = document.createElement("div");
  win.id = "ntpc-window";
  win.innerHTML = `
    <div id="ntpc-header">
      <div>⚡ NTPC Assistant<br><span style="font-size:11px;font-weight:normal;">● Online · Powered by AI</span></div>
      <button id="ntpc-close" style="border:none;background:rgba(255,255,255,0.2);color:white;border-radius:50%;width:30px;height:30px;cursor:pointer;">×</button>
    </div>

    <div id="ntpc-messages"></div>

    <div id="ntpc-input-area">
      <input id="ntpc-input" placeholder="Ask anything about NTPC..." />
      <button id="ntpc-send">➤</button>
    </div>
  `;
  document.body.appendChild(win);

  const messages = document.getElementById("ntpc-messages");
  const input = document.getElementById("ntpc-input");
  const sendBtn = document.getElementById("ntpc-send");

  function addBot(text) {
    const div = document.createElement("div");
    div.className = "ntpc-bot";
    div.textContent = text;
    messages.appendChild(div);
    messages.scrollTop = messages.scrollHeight;
  }

  function addUser(text) {
    const div = document.createElement("div");
    div.className = "ntpc-user";
    div.textContent = text;
    messages.appendChild(div);
    messages.scrollTop = messages.scrollHeight;
  }

  async function sendMessage() {
    const question = input.value.trim();
    if (!question) return;

    input.value = "";
    addUser(question);

    const loading = document.createElement("div");
    loading.className = "ntpc-bot";
    loading.textContent = "Thinking...";
    messages.appendChild(loading);

    try {
      const res = await fetch(`${BACKEND_URL}/chat`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json"
        },
        body: JSON.stringify({
          question: question
        })
      });

      const data = await res.json();
      loading.remove();

      addBot(data.answer || data.response || "Sorry, answer nahi mila.");
    } catch (err) {
      loading.remove();
      addBot("⚠️ Backend se connect nahi ho pa raha. Port 8000 check karo.");
      console.error(err);
    }
  }

  fab.addEventListener("click", function () {
    win.style.display = "flex";
    fab.style.display = "none";
  });

  document.getElementById("ntpc-close").addEventListener("click", function () {
    win.style.display = "none";
    fab.style.display = "block";
  });

  sendBtn.addEventListener("click", sendMessage);

  input.addEventListener("keydown", function (e) {
    if (e.key === "Enter") {
      e.preventDefault();
      sendMessage();
    }
  });

  addBot("Namaste! 🙏 I am NTPC's AI Assistant. Ask me anything about NTPC reports.");
})();
