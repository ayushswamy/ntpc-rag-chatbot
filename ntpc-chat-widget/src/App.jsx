import ChatWidget from "./ChatWidget";

export default function App() {
  return (
    <div style={{
      minHeight:"100vh",
      background:"#f0f4f0",
      display:"flex",
      alignItems:"center",
      justifyContent:"center"
    }}>
      <div style={{ textAlign:"center", color:"#555" }}>
        <h1 style={{ fontFamily:"sans-serif", color:"#00A651", marginBottom:8 }}>
          NTPC Chatbot Widget
        </h1>
        <p style={{ fontFamily:"sans-serif", fontSize:14 }}>
          👇 Click the green button (bottom-right) to open!
        </p>
      </div>
      <ChatWidget/>
    </div>
  );
}