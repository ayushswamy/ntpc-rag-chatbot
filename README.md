<div align="center">

<img src="https://readme-typing-svg.herokuapp.com?font=Fira+Code&size=32&duration=3000&pause=1000&color=00D4FF&center=true&vCenter=true&width=600&lines=NTPC+RAG+Chatbot+%F0%9F%A4%96;AI-Powered+Document+QA;Built+with+Python+%2B+Next.js" alt="Typing SVG" />

<br/>

[![Python](https://img.shields.io/badge/Python-3.12+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![Next.js](https://img.shields.io/badge/Next.js-15-000000?style=for-the-badge&logo=nextdotjs&logoColor=white)](https://nextjs.org)
[![ChromaDB](https://img.shields.io/badge/ChromaDB-Vector_DB-FF6B6B?style=for-the-badge&logo=databricks&logoColor=white)](https://trychroma.com)
[![RAG](https://img.shields.io/badge/RAG-Architecture-00D4FF?style=for-the-badge&logo=openai&logoColor=white)](https://github.com)
[![License](https://img.shields.io/badge/License-MIT-green?style=for-the-badge)](LICENSE)

<br/>

> **Ask anything about NTPC — annual reports, financials, operations, and more.**
> Powered by Retrieval-Augmented Generation (RAG) for accurate, source-backed answers.

<br/>

[🚀 Getting Started](#getting-started) • [✨ Features](#features) • [🏗️ Architecture](#architecture) • [📖 Usage](#usage)

---

</div>

## ✨ Features

| Feature | Description |
|--------|-------------|
| 🔍 **Smart Retrieval** | Finds the most relevant sections from NTPC annual reports |
| 📄 **Multi-Year Coverage** | Annual reports from 2017 to 2025 |
| 🧠 **RAG Pipeline** | Combines vector search with LLM for accurate answers |
| ⚡ **ChromaDB** | Lightning-fast vector similarity search |
| 🌐 **Modern UI** | Clean, responsive Next.js frontend |
| 🔒 **Source-backed** | Every answer is grounded in real NTPC documents |

---

## 🏗️ Architecture


User Question
│
▼
┌─────────────────┐
│   Next.js UI    │  ◄── Beautiful chat interface
└────────┬────────┘
│ API Call
▼
┌─────────────────┐
│  FastAPI Server │  ◄── Python backend
└────────┬────────┘
│
┌────┴────┐
▼         ▼
┌────────┐ ┌──────────┐
│ChromaDB│ │  LLM API │
│Vectors │ │          │
└────┬───┘ └────┬─────┘
│           │
└─────┬─────┘
▼
┌─────────────┐
│   Answer    │  ◄── Grounded in NTPC documents
└─────────────┘

---

## 🛠️ Tech Stack

| Layer | Technology |
|-------|-----------|
| **Frontend** | Next.js 15, React, Tailwind CSS |
| **Backend** | Python 3.12, FastAPI |
| **Vector DB** | ChromaDB |
| **Embeddings** | Sentence Transformers |
| **Documents** | NTPC Annual Reports (PDF) |

---

## 📁 Project Structure
ntpc-rag-chatbot/
│
├── 📂 backend/
│   ├── main.py          # FastAPI server & API routes
│   ├── rag.py           # Core RAG pipeline
│   ├── embedder.py      # Document chunking & embedding
│   ├── scraper.py       # PDF data extraction
│   └── indexer.py       # ChromaDB indexing
│
├── 📂 frontend/
│   └── app/
│       ├── page.tsx     # Chat interface
│       ├── layout.tsx   # App layout
│       └── globals.css  # Styles
│
├── 📂 data/
│   └── reports/         # NTPC Annual Reports (PDF)
│
├── 📂 scripts/          # Utility scripts
├── .env                 # Environment variables
├── .gitignore
└── README.md

---

## 🚀 Getting Started

### Prerequisites
- **Python** 3.12+
- **Node.js** 18+

### 1️⃣ Clone the Repository
```bash
git clone https://github.com/AyushKumar-2006/ntpc-rag-chatbot.git
cd ntpc-rag-chatbot
```

### 2️⃣ Set Up the Backend
```bash
cd backend
pip install -r requirements.txt
```

### 3️⃣ Configure Environment
```bash
cp .env.example .env
# Open .env and add your API keys
```

### 4️⃣ Set Up the Frontend
```bash
cd ../frontend
npm install
```

### 5️⃣ Run the App

**Terminal 1 — Backend:**
```bash
cd backend
python main.py
```

**Terminal 2 — Frontend:**
```bash
cd frontend
npm run dev
```

Open → [http://localhost:3000](http://localhost:3000) 🎉

---

## 📖 Usage
💬 "What was NTPC's total revenue in 2023-24?"
💬 "How many MW of installed capacity does NTPC have?"
💬 "What are NTPC's renewable energy targets for 2032?"
💬 "Summarize the key highlights from the 2024-25 annual report."
💬 "What is NTPC's dividend history over the last 5 years?"

---

## 📊 Data Sources

| Report | Year |
|--------|------|
| NTPC Annual Report | 2024–25 |
| NTPC Annual Report | 2023–24 |
| NTPC Annual Report | 2021–22 |
| NTPC Annual Report | 2018–19 |
| NTPC Annual Report | 2017–18 |

---

## 🤝 Contributing

```bash
git checkout -b feature/your-feature
git commit -m "Add your feature"
git push origin feature/your-feature
```

---

## 📄 License

MIT License — see [LICENSE](LICENSE) for details.

---

<div align="center">

Made with  by Ayush Swamy

⭐ **Star this repo if you found it helpful!**

</div>
