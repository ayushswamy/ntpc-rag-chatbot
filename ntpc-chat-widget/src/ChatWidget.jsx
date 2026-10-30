import { useState, useRef, useEffect } from "react";
import { MessageCircle, X, Send, Loader2, Zap } from "lucide-react";

const BACKEND_URL = "http://localhost:8000";

const suggestedQuestions = [
  "What is NTPC's total installed capacity?",
  "Tell me about NTPC's renewable energy plans",
  "What are NTPC's sustainability initiatives?",
  "NTPC revenue in latest annual report",
];

function TypingDots() {
  return (
    <div style={{ display:"flex", gap:4, alignItems:"center", padding:"10px 14px" }}>
      {[0,1,2].map((i) => (
        <span key={i} style={{
          width:7, height:7, borderRadius:"50%", background:"#00A651",
          display:"inline-block", animation:"bounce 1.2s infinite",
          animationDelay:`${i*0.2}s`,
        }}/>
      ))}
    </div>
  );
}

export default function ChatWidget() {
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState([{
    role:"assistant",
    text:"Namaste! 🙏 I'm NTPC's AI assistant. Ask me anything about NTPC's reports, sustainability, financials, and more!",
  }]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const bottomRef = useRef(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior:"smooth" });
  }, [messages, loading]);

  async function sendMessage(text) {
    const question = text || input.trim();
    if (!question) return;
    setInput("");
    setMessages((prev) => [...prev, { role:"user", text:question }]);
    setLoading(true);
    try {
      const res = await fetch(`${BACKEND_URL}/chat`, {
        method:"POST",
        headers:{ "Content-Type":"application/json" },
        body: JSON.stringify({ question }),
      });
      const data = await res.json();
      const reply = data.response || data.answer || "Sorry, I couldn't find an answer.";
      setMessages((prev) => [...prev, { role:"assistant", text:reply, sources:data.sources }]);
    } catch {
      setMessages((prev) => [...prev, {
        role:"assistant",
        text:"⚠️ Backend se connect nahi ho pa raha. Server check karo.",
      }]);
    } finally {
      setLoading(false);
    }
  }

  return (
    <>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600&display=swap');
        @keyframes bounce {
          0%,80%,100%{transform:scale(0.7);opacity:0.5}
          40%{transform:scale(1);opacity:1}
        }
        @keyframes slideUp {
          from{opacity:0;transform:translateY(20px) scale(0.97)}
          to{opacity:1;transform:translateY(0) scale(1)}
        }
        @keyframes popIn {
          from{transform:scale(0.5);opacity:0}
          to{transform:scale(1);opacity:1}
        }
        @keyframes spin {
          from{transform:rotate(0deg)}
          to{transform:rotate(360deg)}
        }
        .chat-window{animation:slideUp 0.3s cubic-bezier(0.34,1.56,0.64,1)}
        .fab{animation:popIn 0.4s cubic-bezier(0.34,1.56,0.64,1);transition:transform 0.2s ease}
        .fab:hover{transform:scale(1.08)}
        .suggestion-chip:hover{background:#e8f5ee !important;border-color:#00A651 !important}
        textarea:focus{outline:none}
        ::-webkit-scrollbar{width:4px}
        ::-webkit-scrollbar-thumb{background:#d0d0d0;border-radius:4px}
      `}</style>

      {/* Floating Button */}
      {!open && (
        <button className="fab" onClick={() => setOpen(true)} style={{
          position:"fixed", bottom:28, right:28, zIndex:9999,
          width:60, height:60, borderRadius:"50%", border:"none",
          background:"linear-gradient(135deg,#00A651 0%,#007a3c 100%)",
          color:"#fff", cursor:"pointer",
          boxShadow:"0 4px 20px rgba(0,166,81,0.4)",
          display:"flex", alignItems:"center", justifyContent:"center",
        }}>
          <MessageCircle size={26}/>
        </button>
      )}

      {/* Chat Window */}
      {open && (
        <div className="chat-window" style={{
          position:"fixed", bottom:24, right:24, zIndex:9999,
          width:380, height:580, borderRadius:20, background:"#fff",
          boxShadow:"0 20px 60px rgba(0,0,0,0.18)",
          display:"flex", flexDirection:"column",
          fontFamily:"'DM Sans', sans-serif", overflow:"hidden",
        }}>
          {/* Header */}
          <div style={{
            background:"linear-gradient(135deg,#00A651 0%,#007a3c 100%)",
            padding:"16px 18px", display:"flex", alignItems:"center",
            justifyContent:"space-between",
          }}>
            <div style={{ display:"flex", alignItems:"center", gap:10 }}>
              <div style={{
                width:38, height:38, borderRadius:"50%",
                background:"rgba(255,255,255,0.2)",
                display:"flex", alignItems:"center", justifyContent:"center",
              }}>
                <Zap size={20} color="#fff" fill="#fff"/>
              </div>
              <div>
                <div style={{ color:"#fff", fontWeight:600, fontSize:15 }}>NTPC Assistant</div>
                <div style={{ color:"rgba(255,255,255,0.75)", fontSize:11, display:"flex", alignItems:"center", gap:4 }}>
                  <span style={{ width:6, height:6, borderRadius:"50%", background:"#90ff90", display:"inline-block" }}/>
                  Online · Powered by AI
                </div>
              </div>
            </div>
            <button onClick={() => setOpen(false)} style={{
              background:"rgba(255,255,255,0.15)", border:"none",
              borderRadius:"50%", width:32, height:32, cursor:"pointer",
              display:"flex", alignItems:"center", justifyContent:"center", color:"#fff",
            }}>
              <X size={16}/>
            </button>
          </div>

          {/* Messages */}
          <div style={{
            flex:1, overflowY:"auto", padding:"16px 14px",
            display:"flex", flexDirection:"column", gap:10,
          }}>
            {messages.map((msg,i) => (
              <div key={i} style={{
                display:"flex",
                justifyContent: msg.role==="user" ? "flex-end" : "flex-start",
              }}>
                <div style={{
                  maxWidth:"82%", minWidth:0, padding:"10px 14px",
                  borderRadius: msg.role==="user" ? "18px 18px 4px 18px" : "18px 18px 18px 4px",
                  background: msg.role==="user" ? "linear-gradient(135deg,#00A651,#007a3c)" : "#f4f4f4",
                  color: msg.role==="user" ? "#fff" : "#222",
                  fontSize:13.5, lineHeight:1.55,
                  overflowWrap:"anywhere", wordBreak:"break-word", whiteSpace:"pre-wrap",
                }}>
                  {msg.text}
                  {msg.sources?.length > 0 && (
                    <div style={{ marginTop:6, fontSize:11, color:"#888", overflowWrap:"anywhere", wordBreak:"break-word" }}>
                      📄 {msg.sources[0].source}
                    </div>
                  )}
                </div>
              </div>
            ))}

            {loading && (
              <div style={{ display:"flex", justifyContent:"flex-start" }}>
                <div style={{ background:"#f4f4f4", borderRadius:"18px 18px 18px 4px" }}>
                  <TypingDots/>
                </div>
              </div>
            )}

            {/* Suggested questions */}
            {messages.length === 1 && (
              <div style={{ marginTop:8 }}>
                <div style={{ fontSize:11, color:"#999", marginBottom:8, fontWeight:500 }}>
                  SUGGESTED QUESTIONS
                </div>
                <div style={{ display:"flex", flexDirection:"column", gap:6 }}>
                  {suggestedQuestions.map((q,i) => (
                    <button key={i} className="suggestion-chip"
                      onClick={() => sendMessage(q)}
                      style={{
                        background:"#f9fdf9", border:"1px solid #d4edda",
                        borderRadius:10, padding:"8px 12px", cursor:"pointer",
                        fontSize:12.5, color:"#1a6636", textAlign:"left",
                        fontFamily:"'DM Sans', sans-serif", transition:"all 0.15s",
                      }}>
                      {q}
                    </button>
                  ))}
                </div>
              </div>
            )}
            <div ref={bottomRef}/>
          </div>

          {/* Input */}
          <div style={{
            padding:"12px 14px", borderTop:"1px solid #f0f0f0",
            display:"flex", gap:8, alignItems:"flex-end", background:"#fff",
          }}>
            <textarea rows={1} value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if(e.key==="Enter" && !e.shiftKey){ e.preventDefault(); sendMessage(); }
              }}
              placeholder="Ask anything about NTPC..."
              style={{
                flex:1, resize:"none", border:"1.5px solid #e8e8e8",
                borderRadius:12, padding:"10px 14px", fontSize:13.5,
                fontFamily:"'DM Sans', sans-serif", lineHeight:1.5,
                background:"#fafafa", color:"#222",
              }}
            />
            <button onClick={() => sendMessage()}
              disabled={loading || !input.trim()}
              style={{
                width:40, height:40, borderRadius:"50%", border:"none",
                background:"#00A651", color:"#fff", cursor:"pointer",
                display:"flex", alignItems:"center", justifyContent:"center",
                opacity: loading || !input.trim() ? 0.5 : 1, flexShrink:0,
              }}>
              {loading
                ? <Loader2 size={16} style={{ animation:"spin 1s linear infinite" }}/>
                : <Send size={16}/>
              }
            </button>
          </div>
        </div>
      )}
    </>
  );
}