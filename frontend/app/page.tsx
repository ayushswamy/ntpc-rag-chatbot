"use client";

import { useState } from "react";

type Report = {
  year: string;
  title: string;
  size: string;
  file: string;
  link: string;
};

type Source = {
  title?: string;
  url?: string;
};

type Message = {
  role: "bot" | "user";
  content: string;
  sources?: Source[];
  followups?: string[];
};

const BACKEND = "http://localhost:8000";

const reports: Report[] = [
  {
    year: "2024-25",
    title: "Annual Report 2024-25",
    size: "32.6 MB",
    file: "Annual Report 2024-25_1.pdf",
    link: "/reports/Annual%20Report%202024-25_1.pdf",
  },
  {
    year: "2023-24",
    title: "Annual Report 2023-24",
    size: "22.1 MB",
    file: "Annual Report 2023-24.pdf",
    link: "/reports/Annual%20Report%202023-24.pdf",
  },
  {
    year: "2022-23",
    title: "Annual Report 2022-23",
    size: "19.4 MB",
    file: "47th Annual Report of NTPC 2022-2023 New.pdf",
    link: "/reports/47th%20Annual%20Report%20of%20NTPC%202022-2023%20New.pdf",
  },
  {
    year: "2021-22",
    title: "Annual Report 2021-22",
    size: "21.5 MB",
    file: "Annual-Report-2021-22.pdf",
    link: "/reports/Annual-Report-2021-22.pdf",
  },
  {
    year: "2020-21",
    title: "Annual Report 2020-2021",
    size: "18.8 MB",
    file: "NTPC_Annual Report_20-21.pdf",
    link: "/reports/NTPC_Annual%20Report_20-21.pdf",
  },
  {
    year: "2019-20",
    title: "Annual Report 2019-20",
    size: "17.9 MB",
    file: "44-final-NTPC-AR-30082020.pdf",
    link: "/reports/44-final-NTPC-AR-30082020.pdf",
  },
  {
    year: "2018-19",
    title: "Annual Report 2018-19",
    size: "16.8 MB",
    file: "annual-report-2018-19.pdf",
    link: "/reports/annual-report-2018-19.pdf",
  },
  {
    year: "2017-18",
    title: "Annual Report 2017-18",
    size: "15.5 MB",
    file: "2017-18.pdf",
    link: "/reports/2017-18.pdf",
  },
];

const initialMessages: Message[] = [
  {
    role: "bot",
    content:
      "👋 Hello! I'm the NTPC AI Assistant. Ask me anything about NTPC Annual Reports, financial performance, installed capacity, or any other investor information.",
    followups: ["Latest Annual Report", "Revenue highlights", "Capacity addition"],
  },
];

function ReportCard({ report }: { report: Report }) {
  return (
    <div className="ntpc-report-card">
      {/* Branded cover placeholder (NO embedded PDF) - embedding the PDF in an
          iframe makes browsers that are set to "download PDFs" auto-download
          every report on page load. The card opens the PDF on a user click. */}
      <a href={report.link} target="_blank" rel="noreferrer" className="ntpc-cover">
        <div className="ntpc-cover-fallback">
          <span className="ntpc-cover-icon">📄</span>
          <span className="ntpc-cover-year">{report.year}</span>
          <span className="ntpc-cover-label">Annual Report</span>
        </div>
      </a>

      <a href={report.link} target="_blank" rel="noreferrer" className="ntpc-report-title">
        {report.title}
      </a>

      <div className="ntpc-report-size">({report.size})</div>
    </div>
  );
}

export default function Page() {
  const [chatOpen, setChatOpen] = useState(false);
  const [chatInput, setChatInput] = useState("");
  const [messages, setMessages] = useState<Message[]>(initialMessages);
  const [typing, setTyping] = useState(false);

  const toggleChat = () => setChatOpen((prev) => !prev);

  const appendMessage = (message: Message) => {
    setMessages((prev) => [...prev, message]);
  };

  const sendMessage = async (customText?: string) => {
    const text = (customText ?? chatInput).trim();
    if (!text) return;

    setChatInput("");
    appendMessage({ role: "user", content: text });
    setTyping(true);

    try {
      const res = await fetch(`${BACKEND}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: text }),
      });

      setTyping(false);

      if (res.ok) {
        const data = await res.json();
        appendMessage({
          role: "bot",
          content: data.response || data.answer || JSON.stringify(data),
          sources: data.sources,
          followups: data.follow_up_questions || data.followups,
        });
      } else {
        appendMessage({
          role: "bot",
          content: `⚠️ Server error (${res.status}). Make sure your backend is running at ${BACKEND}`,
        });
      }
    } catch {
      setTyping(false);
      appendMessage({
        role: "bot",
        content: `⚠️ Could not connect to backend at ${BACKEND}. Please start your server.`,
      });
    }
  };

  const sendChip = (text: string) => {
    void sendMessage(text);
  };

  return (
    <>
      <style jsx global>{`
        * {
          margin: 0;
          padding: 0;
          box-sizing: border-box;
        }

        body {
          font-family: Arial, sans-serif;
          font-size: 14px;
          color: #222;
          background: #fff;
        }

        a {
          text-decoration: none;
          color: inherit;
        }

        .util-bar {
          background: #003b70;
          color: #fff;
          font-size: 12px;
          padding: 5px 0;
        }

        .util-bar .inner {
          max-width: 1200px;
          margin: 0 auto;
          padding: 0 15px;
          display: flex;
          justify-content: space-between;
          align-items: center;
        }

        .util-bar a {
          color: #fff;
          margin-right: 12px;
          font-size: 12px;
        }

        .util-right {
          display: flex;
          align-items: center;
          gap: 8px;
        }

        .lang-btn,
        .contrast-btn,
        .font-ctrl button {
          background: transparent;
          color: #fff;
          border: 1px solid rgba(255, 255, 255, 0.7);
          padding: 3px 8px;
          border-radius: 2px;
          cursor: pointer;
          font-size: 12px;
        }

        .lang-btn.active,
        .lang-btn:hover,
        .contrast-btn:hover,
        .font-ctrl button:hover {
          background: #fff;
          color: #003b70;
        }

        .font-ctrl {
          display: flex;
          gap: 4px;
        }

        header {
          background: #fff;
          padding: 11px 0;
          border-bottom: 1px solid #e2e2e2;
        }

        .header-inner {
          max-width: 1200px;
          margin: 0 auto;
          padding: 0 15px;
          display: flex;
          align-items: center;
          justify-content: space-between;
        }

        .logo-wrap {
          display: flex;
          align-items: center;
          gap: 14px;
        }

        .ntpc-logo {
          background: #003b70;
          color: #fff;
          font-size: 32px;
          font-weight: 900;
          padding: 10px 22px;
          letter-spacing: 5px;
          font-style: italic;
        }

        .logo-text {
          display: flex;
          flex-direction: column;
        }

        .logo-text .name {
          color: #003b70;
          font-size: 24px;
          font-weight: 700;
        }

        .logo-text .tagline {
          font-size: 12px;
          color: #777;
          margin-top: 4px;
        }

        .header-right {
          display: flex;
          align-items: center;
          gap: 12px;
        }

        .search-box {
          display: flex;
          border: 1px solid #cfcfcf;
          overflow: hidden;
          border-radius: 2px;
        }

        .search-box input {
          width: 220px;
          border: none;
          outline: none;
          padding: 10px 12px;
          font-size: 14px;
        }

        .search-box button {
          border: none;
          background: #003b70;
          color: #fff;
          padding: 0 14px;
          cursor: pointer;
        }

        .ask-ai-btn {
          background: #e8a000;
          color: #fff;
          border: none;
          padding: 10px 16px;
          border-radius: 3px;
          font-weight: 700;
          cursor: pointer;
          display: flex;
          align-items: center;
          gap: 6px;
        }

        nav {
          background: #003b70;
          position: relative;
          z-index: 50;
        }

        .nav-inner {
          max-width: 1200px;
          margin: 0 auto;
          padding: 0 15px;
        }

        .nav-list {
          display: flex;
          list-style: none;
        }

        .nav-list > li {
          position: relative;
        }

        .nav-list > li > a {
          display: block;
          color: #fff;
          padding: 16px 22px;
          font-weight: 700;
          font-size: 15px;
        }

        .nav-list > li.active > a,
        .nav-list > li > a:hover {
          background: #e8a000;
        }

        .dropdown {
          display: none;
          position: absolute;
          top: 100%;
          left: 0;
          min-width: 240px;
          background: #fff;
          list-style: none;
          box-shadow: 0 5px 15px rgba(0, 0, 0, 0.18);
          border-top: 3px solid #e8a000;
        }

        .nav-list > li:hover .dropdown {
          display: block;
        }

        .dropdown a {
          display: block;
          padding: 10px 15px;
          color: #222;
          font-size: 13px;
          border-bottom: 1px solid #eee;
        }

        .dropdown a:hover,
        .dropdown .active a {
          background: #003b70;
          color: #fff;
        }

        .banner {
          height: 205px;
          background: linear-gradient(135deg, #004c94 0%, #007980 45%, #00923f 75%, #e0a700 100%);
          position: relative;
          overflow: hidden;
        }

        .banner-content {
          max-width: 1200px;
          margin: 0 auto;
          height: 100%;
          display: flex;
          align-items: center;
          padding: 0 15px;
        }

        .banner-title {
          color: #fff;
          font-size: 32px;
          font-weight: 700;
          text-shadow: 1px 2px 4px rgba(0, 0, 0, 0.35);
          letter-spacing: 1px;
        }

        .banner-illus {
          position: absolute;
          right: 75px;
          top: 50%;
          transform: translateY(-50%);
          display: flex;
          align-items: flex-end;
          gap: 32px;
          opacity: 0.75;
        }

        .breadcrumb {
          background: #f4f4f4;
          border-bottom: 1px solid #d9d9d9;
        }

        .breadcrumb-inner {
          max-width: 1200px;
          margin: 0 auto;
          padding: 13px 15px;
          font-size: 14px;
          color: #555;
        }

        .breadcrumb-inner a {
          color: #0067a8;
        }

        .breadcrumb-inner span {
          color: #d9a000;
          margin: 0 8px;
        }

        .ntpc-main {
          max-width: 1200px;
          margin: 0 auto;
          padding: 55px 15px 85px;
          display: grid;
          grid-template-columns: 230px 1fr;
          gap: 42px;
          align-items: start;
        }

        .ntpc-left-menu {
          background: #e8ffe9;
          border-radius: 12px 12px 0 0;
          padding: 22px 16px;
          min-height: 230px;
        }

        .ntpc-left-menu a {
          display: block;
          color: #111;
          font-size: 18px;
          line-height: 1.22;
          font-weight: 700;
          padding: 6px 0;
          border-bottom: 1px solid #6c8f72;
        }

        .ntpc-left-menu a.active {
          color: #0067a8;
        }

        .ntpc-reports-grid {
          display: grid;
          grid-template-columns: repeat(4, 1fr);
          gap: 54px 58px;
        }

        .ntpc-report-card {
          text-align: center;
          min-width: 0;
        }

        .ntpc-cover {
          width: 180px;
          height: 235px;
          display: block;
          margin: 0 auto 12px;
          background: #f6f6f6;
          overflow: hidden;
          border: 1px solid #ddd;
          box-shadow: 0 2px 7px rgba(0, 0, 0, 0.15);
        }

        .ntpc-cover-fallback {
          width: 100%;
          height: 100%;
          display: flex;
          flex-direction: column;
          align-items: center;
          justify-content: center;
          gap: 8px;
          background: linear-gradient(160deg, #0071bc, #00488a);
          color: #fff;
          text-align: center;
        }

        .ntpc-cover-icon {
          font-size: 46px;
        }

        .ntpc-cover-year {
          font-size: 26px;
          font-weight: 700;
          letter-spacing: 0.5px;
        }

        .ntpc-cover-label {
          font-size: 12px;
          opacity: 0.85;
          text-transform: uppercase;
          letter-spacing: 1px;
        }

        .ntpc-pdf-small {
          font-size: 15px;
          margin: 4px 0 3px;
        }

        .ntpc-report-title {
          display: block;
          color: #0071bc;
          font-size: 22px;
          line-height: 1.16;
          font-weight: 600;
          margin: 0 auto;
        }

        .ntpc-report-title:hover {
          text-decoration: underline;
        }

        .ntpc-report-size {
          margin-top: 8px;
          color: #111;
          font-size: 15px;
          font-weight: 700;
        }

        footer {
          background: #003b70;
          color: #fff;
        }

        .footer-top {
          padding: 30px 0 20px;
        }

        .footer-inner {
          max-width: 1200px;
          margin: 0 auto;
          padding: 0 15px;
        }

        .footer-cols {
          display: grid;
          grid-template-columns: 210px 1fr 1fr 1fr 1fr;
          gap: 25px;
        }

        .ntpc-logo-f {
          background: #fff;
          color: #003b70;
          display: inline-block;
          padding: 8px 18px;
          font-size: 22px;
          font-weight: 900;
          letter-spacing: 4px;
          font-style: italic;
        }

        .footer-logo-block p,
        .footer-address {
          color: #bfd4ea;
          font-size: 12px;
          line-height: 1.55;
          margin-top: 10px;
        }

        .footer-social {
          display: flex;
          gap: 10px;
          margin-top: 13px;
        }

        .footer-social a {
          width: 32px;
          height: 32px;
          background: rgba(255, 255, 255, 0.12);
          display: flex;
          align-items: center;
          justify-content: center;
          color: #fff;
          border-radius: 3px;
        }

        .footer-col h4 {
          color: #e8a000;
          font-size: 13px;
          text-transform: uppercase;
          margin-bottom: 12px;
          padding-bottom: 8px;
          border-bottom: 1px solid rgba(255, 255, 255, 0.22);
        }

        .footer-col ul {
          list-style: none;
        }

        .footer-col li {
          margin-bottom: 8px;
        }

        .footer-col a {
          color: #bfd4ea;
          font-size: 13px;
        }

        .footer-col a:hover {
          color: #fff;
          text-decoration: underline;
        }

        .footer-bottom {
          background: #00264f;
          text-align: center;
          color: #bfd4ea;
          font-size: 12px;
          padding: 12px 0;
        }

        .footer-bottom a {
          color: #e8a000;
        }

        #chat-fab {
          position: fixed;
          bottom: 30px;
          right: 30px;
          width: 58px;
          height: 58px;
          border: none;
          border-radius: 50%;
          background: #003b70;
          display: flex;
          align-items: center;
          justify-content: center;
          cursor: pointer;
          box-shadow: 0 4px 18px rgba(0, 0, 0, 0.28);
          z-index: 999;
        }

        #chat-fab svg {
          width: 27px;
          height: 27px;
          fill: #fff;
        }

        #chat-badge {
          position: absolute;
          top: -5px;
          right: -5px;
          background: #e8a000;
          color: #fff;
          font-size: 10px;
          font-weight: 700;
          padding: 3px 6px;
          border-radius: 10px;
        }

        #chat-window {
          position: fixed;
          bottom: 100px;
          right: 30px;
          width: 390px;
          max-height: 520px;
          background: #fff;
          border-radius: 10px;
          box-shadow: 0 8px 32px rgba(0, 0, 0, 0.23);
          display: none;
          flex-direction: column;
          overflow: hidden;
          z-index: 998;
        }

        #chat-window.open {
          display: flex;
        }

        .chat-header {
          background: #003b70;
          color: #fff;
          padding: 13px 16px;
          display: flex;
          justify-content: space-between;
          align-items: center;
        }

        .chat-header-left {
          display: flex;
          align-items: center;
          gap: 10px;
        }

        .chat-avatar {
          width: 35px;
          height: 35px;
          border-radius: 50%;
          background: #e8a000;
          display: flex;
          align-items: center;
          justify-content: center;
          font-weight: 700;
        }

        .chat-hname {
          font-size: 14px;
          font-weight: 700;
        }

        .chat-hstatus {
          font-size: 11px;
          color: #bfd4ea;
        }

        .chat-close {
          border: none;
          background: transparent;
          color: #fff;
          font-size: 22px;
          cursor: pointer;
        }

        .chat-messages {
          flex: 1;
          overflow-y: auto;
          padding: 14px;
          display: flex;
          flex-direction: column;
          gap: 10px;
          background: #f7f9fc;
          min-height: 210px;
          max-height: 320px;
        }

        .msg {
          max-width: 86%;
          padding: 10px 13px;
          border-radius: 10px;
          font-size: 13px;
          line-height: 1.5;
          min-width: 0;
          overflow-wrap: anywhere;
          word-break: break-word;
          white-space: pre-wrap;
        }

        .msg.bot {
          background: #fff;
          border: 1px solid #dbe4f0;
          color: #222;
          align-self: flex-start;
          border-radius: 2px 10px 10px 10px;
        }

        .msg.user {
          background: #003b70;
          color: #fff;
          align-self: flex-end;
          border-radius: 10px 2px 10px 10px;
        }

        .msg-sources {
          margin-top: 6px;
          font-size: 11px;
        }

        .msg-sources a {
          display: block;
          color: #003b70;
          text-decoration: underline;
          overflow-wrap: anywhere;
          word-break: break-word;
        }

        .followup-chips,
        .quick-chips {
          display: flex;
          flex-wrap: wrap;
          gap: 6px;
        }

        .followup-chips {
          margin-top: 8px;
        }

        .quick-chips {
          padding: 9px 14px;
          background: #f7f9fc;
          border-top: 1px solid #e0e8f0;
        }

        .quick-chips span {
          font-size: 11px;
          color: #888;
          margin-right: 5px;
        }

        .chip {
          background: #e8f0fe;
          color: #003b70;
          font-size: 11px;
          padding: 5px 11px;
          border: 1px solid #bed0ef;
          border-radius: 14px;
          cursor: pointer;
        }

        .chip:hover {
          background: #003b70;
          color: #fff;
        }

        .typing {
          display: flex;
          gap: 4px;
          padding: 8px 12px;
        }

        .typing span {
          width: 7px;
          height: 7px;
          background: #aac4e0;
          border-radius: 50%;
          animation: bounce 1s infinite;
        }

        .typing span:nth-child(2) {
          animation-delay: 0.15s;
        }

        .typing span:nth-child(3) {
          animation-delay: 0.3s;
        }

        @keyframes bounce {
          0%,
          80%,
          100% {
            transform: translateY(0);
          }

          40% {
            transform: translateY(-6px);
          }
        }

        .chat-input-row {
          display: flex;
          gap: 8px;
          padding: 11px 12px;
          border-top: 1px solid #e0e8f0;
          background: #fff;
        }

        .chat-input-row input {
          flex: 1;
          border: 1px solid #cdd5e0;
          border-radius: 20px;
          padding: 9px 14px;
          outline: none;
          font-size: 13px;
        }

        .chat-send {
          width: 37px;
          height: 37px;
          border-radius: 50%;
          border: none;
          background: #003b70;
          display: flex;
          align-items: center;
          justify-content: center;
          cursor: pointer;
        }

        .chat-send svg {
          width: 16px;
          height: 16px;
          fill: #fff;
        }

        @media (max-width: 1000px) {
          .ntpc-main {
            grid-template-columns: 1fr;
          }

          .ntpc-reports-grid {
            grid-template-columns: repeat(2, 1fr);
          }

          .footer-cols {
            grid-template-columns: 1fr 1fr;
          }
        }

        @media (max-width: 650px) {
          .header-inner,
          .util-bar .inner {
            flex-direction: column;
            gap: 10px;
          }

          .nav-list {
            flex-wrap: wrap;
          }

          .ntpc-reports-grid {
            grid-template-columns: 1fr;
          }

          .ntpc-cover {
            width: 170px;
            height: 225px;
          }

          .footer-cols {
            grid-template-columns: 1fr;
          }

          #chat-window {
            right: 12px;
            left: 12px;
            width: auto;
          }
        }
      `}</style>

      <div className="util-bar">
        <div className="inner">
          <div>
            <a href="#">Skip to Main Content</a>
            <a href="#">Screen Reader Access</a>
          </div>
          <div className="util-right">
            <button className="lang-btn active">English</button>
            <button className="lang-btn">Hindi</button>
            <div className="font-ctrl">
              <button>A-</button>
              <button>A</button>
              <button>A+</button>
            </div>
            <button className="contrast-btn">High Contrast</button>
          </div>
        </div>
      </div>

      <header>
        <div className="header-inner">
          <div className="logo-wrap">
            <div className="ntpc-logo">NTPC</div>
            <div className="logo-text">
              <span className="name">NTPC Limited</span>
              <span className="tagline">Powering India&apos;s Growth</span>
            </div>
          </div>

          <div className="header-right">
            <div className="search-box">
              <input type="text" placeholder="Search..." />
              <button>🔍</button>
            </div>
            <button className="ask-ai-btn" onClick={toggleChat}>
              💬 Ask AI
            </button>
          </div>
        </div>
      </header>

      <nav>
        <div className="nav-inner">
          <ul className="nav-list">
            <li>
              <a href="#">Home</a>
            </li>
            <li>
              <a href="#">About Us ▼</a>
              <ul className="dropdown">
                <li>
                  <a href="#">NTPC Overview</a>
                </li>
                <li>
                  <a href="#">Our Journey</a>
                </li>
                <li>
                  <a href="#">Board of Directors</a>
                </li>
                <li>
                  <a href="#">Installed Capacity</a>
                </li>
              </ul>
            </li>
            <li>
              <a href="#">Sustainability ▼</a>
              <ul className="dropdown">
                <li>
                  <a href="#">Approach</a>
                </li>
                <li>
                  <a href="#">Materiality Analysis</a>
                </li>
                <li>
                  <a href="#">Reports and Publications</a>
                </li>
                <li>
                  <a href="#">ESG Disclosure</a>
                </li>
              </ul>
            </li>
            <li className="active">
              <a href="#">Investors ▼</a>
              <ul className="dropdown">
                <li>
                  <a href="#">Chairman&apos;s Statement</a>
                </li>
                <li className="active">
                  <a href="#">Financial Performance</a>
                </li>
                <li>
                  <a href="#">Corporate Governance</a>
                </li>
                <li>
                  <a href="#">Compliances</a>
                </li>
              </ul>
            </li>
            <li>
              <a href="#">Media ▼</a>
            </li>
            <li>
              <a href="#">Join Us ▼</a>
            </li>
          </ul>
        </div>
      </nav>

      <div className="banner">
        <div className="banner-content">
          <h1 className="banner-title">Annual Reports</h1>
        </div>

        <div className="banner-illus">
          <svg width="80" height="100" viewBox="0 0 80 100">
            <rect x="37" y="40" width="6" height="55" fill="rgba(255,255,255,0.75)" rx="2" />
            <g transform="translate(40,40)">
              <line x1="0" y1="0" x2="0" y2="-32" stroke="rgba(255,255,255,0.9)" strokeWidth="3" />
              <line x1="0" y1="0" x2="27.7" y2="16" stroke="rgba(255,255,255,0.9)" strokeWidth="3" />
              <line x1="0" y1="0" x2="-27.7" y2="16" stroke="rgba(255,255,255,0.9)" strokeWidth="3" />
            </g>
          </svg>

          <svg width="70" height="80" viewBox="0 0 70 80">
            <rect x="5" y="10" width="60" height="40" rx="2" fill="none" stroke="rgba(255,255,255,0.75)" strokeWidth="2" />
            <line x1="25" y1="10" x2="25" y2="50" stroke="rgba(255,255,255,0.55)" strokeWidth="1.5" />
            <line x1="45" y1="10" x2="45" y2="50" stroke="rgba(255,255,255,0.55)" strokeWidth="1.5" />
            <line x1="5" y1="24" x2="65" y2="24" stroke="rgba(255,255,255,0.55)" strokeWidth="1.5" />
            <line x1="5" y1="38" x2="65" y2="38" stroke="rgba(255,255,255,0.55)" strokeWidth="1.5" />
            <rect x="30" y="50" width="10" height="20" fill="rgba(255,255,255,0.6)" />
            <rect x="15" y="70" width="40" height="4" rx="1" fill="rgba(255,255,255,0.6)" />
          </svg>

          <svg width="60" height="90" viewBox="0 0 60 90">
            <polygon points="30,5 5,35 55,35" fill="rgba(255,255,255,0.55)" />
            <rect x="10" y="35" width="40" height="50" fill="rgba(255,255,255,0.35)" />
            <rect x="22" y="55" width="16" height="30" fill="rgba(255,255,255,0.55)" />
          </svg>
        </div>
      </div>

      <div className="breadcrumb">
        <div className="breadcrumb-inner">
          <a href="#">Home</a>
          <span>›</span>
          <a href="#">Investors</a>
          <span>›</span>
          <a href="#">Annual Reports</a>
          <span>›</span>
          Annual Reports
        </div>
      </div>

      <section className="ntpc-main">
        <aside className="ntpc-left-menu">
          <a className="active" href="#">
            Annual Reports
          </a>
          <a href="#">
            Financial and <br />
            Operational Highlights at <br />a Glance
          </a>
          <a href="#">Financial Results</a>
          <a href="#">
            Related Party <br />
            Transactions
          </a>
          <a href="#">Annual Returns</a>
          <a href="#">
            Annual Reports of <br />
            Subsidiaries
          </a>
        </aside>

        <main>
          <div className="ntpc-reports-grid">
            {reports.map((report) => (
              <ReportCard key={report.year} report={report} />
            ))}
          </div>
        </main>
      </section>

      <footer>
        <div className="footer-top">
          <div className="footer-inner">
            <div className="footer-cols">
              <div className="footer-logo-block">
                <div className="ntpc-logo-f">NTPC</div>
                <p>
                  NTPC Limited
                  <br />
                  Maharatna Company
                </p>
                <p className="footer-address">
                  NTPC Bhawan, SCOPE Complex,
                  <br />
                  Lodhi Road, New Delhi - 110003
                  <br />
                  India
                </p>
                <div className="footer-social">
                  <a href="#">f</a>
                  <a href="#">𝕏</a>
                  <a href="#">▶</a>
                  <a href="#">in</a>
                  <a href="#">📷</a>
                </div>
              </div>

              <div className="footer-col">
                <h4>About NTPC</h4>
                <ul>
                  <li>
                    <a href="#">NTPC Overview</a>
                  </li>
                  <li>
                    <a href="#">Our Journey</a>
                  </li>
                  <li>
                    <a href="#">Board of Directors</a>
                  </li>
                  <li>
                    <a href="#">Installed Capacity</a>
                  </li>
                </ul>
              </div>

              <div className="footer-col">
                <h4>Sustainability</h4>
                <ul>
                  <li>
                    <a href="#">Approach</a>
                  </li>
                  <li>
                    <a href="#">Materiality Analysis</a>
                  </li>
                  <li>
                    <a href="#">Reports & Publications</a>
                  </li>
                  <li>
                    <a href="#">ESG Disclosure</a>
                  </li>
                </ul>
              </div>

              <div className="footer-col">
                <h4>Investors</h4>
                <ul>
                  <li>
                    <a href="#">Chairman&apos;s Statement</a>
                  </li>
                  <li>
                    <a href="#">Annual Reports</a>
                  </li>
                  <li>
                    <a href="#">Financial Results</a>
                  </li>
                  <li>
                    <a href="#">Corporate Governance</a>
                  </li>
                </ul>
              </div>

              <div className="footer-col">
                <h4>Quick Links</h4>
                <ul>
                  <li>
                    <a href="#">RTI</a>
                  </li>
                  <li>
                    <a href="#">Tenders</a>
                  </li>
                  <li>
                    <a href="#">Vigilance</a>
                  </li>
                  <li>
                    <a href="#">Contact Us</a>
                  </li>
                </ul>
              </div>
            </div>
          </div>
        </div>

        <div className="footer-bottom">
          <div className="footer-inner">
            © 2025 NTPC Limited. All Rights Reserved. | <a href="#">Privacy Policy</a> |{" "}
            <a href="#">Terms of Use</a> | <a href="#">Disclaimer</a> | <a href="#">Sitemap</a>
          </div>
        </div>
      </footer>

      <button id="chat-fab" onClick={toggleChat} title="Ask AI about NTPC Annual Reports">
        <svg viewBox="0 0 24 24">
          <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
        </svg>
        <span id="chat-badge">AI</span>
      </button>

      <div id="chat-window" className={chatOpen ? "open" : ""}>
        <div className="chat-header">
          <div className="chat-header-left">
            <div className="chat-avatar">AI</div>
            <div>
              <div className="chat-hname">NTPC AI Assistant</div>
              <div className="chat-hstatus">● Online — Ask about Annual Reports</div>
            </div>
          </div>
          <button className="chat-close" onClick={toggleChat}>
            ×
          </button>
        </div>

        <div className="chat-messages">
          {messages.map((message, index) => (
            <div className={`msg ${message.role}`} key={`${message.role}-${index}`}>
              {message.content}

              {message.sources && message.sources.length > 0 && (
                <div className="msg-sources">
                  {message.sources.slice(0, 3).map((source, sourceIndex) => (
                    <a href={source.url || "#"} target="_blank" rel="noreferrer" key={sourceIndex}>
                      📄 {source.title || source.url || "Source"}
                    </a>
                  ))}
                </div>
              )}

              {message.followups && message.followups.length > 0 && (
                <div className="followup-chips">
                  {message.followups.map((followup) => (
                    <button className="chip" onClick={() => sendChip(followup)} key={followup}>
                      {followup}
                    </button>
                  ))}
                </div>
              )}
            </div>
          ))}

          {typing && (
            <div className="msg bot">
              <div className="typing">
                <span></span>
                <span></span>
                <span></span>
              </div>
            </div>
          )}
        </div>

        <div className="quick-chips">
          <span>Quick:</span>
          <button className="chip" onClick={() => sendChip("Dividend history")}>
            Dividend history
          </button>
          <button className="chip" onClick={() => sendChip("Green energy")}>
            Green energy
          </button>
          <button className="chip" onClick={() => sendChip("Subsidiaries")}>
            Subsidiaries
          </button>
        </div>

        <div className="chat-input-row">
          <input
            type="text"
            placeholder="Ask about NTPC reports..."
            value={chatInput}
            onChange={(event) => setChatInput(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") void sendMessage();
            }}
          />
          <button className="chat-send" onClick={() => void sendMessage()}>
            <svg viewBox="0 0 24 24">
              <line x1="22" y1="2" x2="11" y2="13" />
              <polygon points="22 2 15 22 11 13 2 9 22 2" />
            </svg>
          </button>
        </div>
      </div>
    </>
  );
}