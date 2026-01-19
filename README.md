# DocPilot - AI Page Summarization Extension

A production-quality browser extension that provides real-time AI-powered page summarization with streaming responses and follow-up question support.

## Features

- 🚀 **Real-time Streaming**: Watch summaries generate token-by-token
- 🧠 **Smart Chunking**: Intelligently splits content by headings and structure
- 🔍 **Semantic Search**: Ask follow-up questions using vector similarity
- 🎯 **Page Classification**: Adapts summarization style to content type (docs, API, blog, README)
- 💾 **Vector Storage**: Reuses embeddings for instant follow-up responses
- 🎨 **Beautiful UI**: Clean overlay with Shadow DOM isolation
- 🔒 **Privacy First**: Uses local LLM - no data sent to external APIs

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     Browser Extension                        │
├─────────────────────────────────────────────────────────────┤
│  Content Script    │  Background SW    │  Overlay (React)   │
│  - Extract text    │  - Handle clicks  │  - Stream UI       │
│  - Inject Shadow   │  - SSE connection │  - Chat interface  │
│  - Forward events  │  - Route messages │  - Status display  │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼ SSE (Server-Sent Events)
┌─────────────────────────────────────────────────────────────┐
│                     FastAPI Backend                          │
├─────────────────────────────────────────────────────────────┤
│  POST /api/summarize        │  POST /api/followup           │
│  - Streaming SSE response   │  - Vector similarity search   │
│  - Progress events          │  - Context-aware answers      │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    LangGraph Agent                           │
├─────────────────────────────────────────────────────────────┤
│  classify_page → chunk_content → embed_store → summarize    │
│       ↓                                           ↓         │
│  Page type detection              Loop until all chunks done│
│       ↓                                           ↓         │
│  docs/api/blog/readme                     merge_summary     │
└─────────────────────────────────────────────────────────────┘
                              │
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
        ┌──────────┐   ┌──────────┐   ┌──────────┐
        │  Ollama  │   │ HuggingFace│  │ Pinecone │
        │ (Mistral)│   │ Embeddings │  │  Vectors │
        └──────────┘   └──────────┘   └──────────┘
```

## Prerequisites

### Required Software

1. **Python 3.11+**
   ```bash
   python --version  # Should be 3.11 or higher
   ```

2. **Node.js 18+**
   ```bash
   node --version  # Should be 18 or higher
   ```

3. **Ollama** (for local LLM)
   - Download from [ollama.ai](https://ollama.ai)
   - Install and run:
   ```bash
   ollama serve
   ollama pull mistral  # or ollama pull llama3:8b
   ```

4. **Pinecone Account** (free tier works)
   - Sign up at [pinecone.io](https://www.pinecone.io)
   - Get your API key from the dashboard

## Installation

### Backend Setup

1. **Navigate to backend directory:**
   ```bash
   cd backend
   ```

2. **Create virtual environment:**
   ```bash
   python -m venv venv
   
   # Windows
   .\venv\Scripts\activate
   
   # macOS/Linux
   source venv/bin/activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure environment:**
   ```bash
   cp .env.example .env
   ```
   
   Edit `.env` and add your Pinecone API key:
   ```env
   PINECONE_API_KEY=your-api-key-here
   DEBUG=true
   ```

5. **Start the server:**
   ```bash
   uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
   ```

### Extension Setup

1. **Navigate to extension directory:**
   ```bash
   cd extension
   ```

2. **Install dependencies:**
   ```bash
   npm install
   ```

3. **Build the extension:**
   ```bash
   npm run build
   ```

4. **Load in Chrome:**
   - Open Chrome and go to `chrome://extensions/`
   - Enable "Developer mode" (top right)
   - Click "Load unpacked"
   - Select the `extension/dist` folder

5. **Create icons** (optional):
   - Add PNG icons to `extension/dist/icons/`:
     - `icon16.png` (16x16)
     - `icon32.png` (32x32)
     - `icon48.png` (48x48)
     - `icon128.png` (128x128)

## Usage

1. **Ensure backend is running:**
   ```bash
   cd backend
   uvicorn app.main:app --reload
   ```

2. **Navigate to any webpage** in Chrome

3. **Click the extension icon** in the toolbar

4. **Watch the summary stream** in the overlay panel

5. **Ask follow-up questions** using the chat interface

## API Endpoints

### Health Check
```bash
GET /api/health
```

### Summarize Page (Streaming)
```bash
POST /api/summarize
Content-Type: application/json

{
  "page_url": "https://example.com/docs",
  "page_text": "...",
  "page_title": "Documentation"
}
```

Response: Server-Sent Events stream
```
event: status
data: {"message": "reading page"}

event: token
data: "The"

event: token
data: " documentation"

event: complete
data: {"summary": "..."}
```

### Follow-up Question (Streaming)
```bash
POST /api/followup
Content-Type: application/json

{
  "page_url": "https://example.com/docs",
  "user_query": "How do I configure authentication?"
}
```

## Project Structure

```
DocPilot/
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py              # FastAPI application
│   │   ├── config.py            # Configuration management
│   │   ├── agent/
│   │   │   ├── __init__.py
│   │   │   ├── state.py         # Agent state schema
│   │   │   ├── nodes.py         # LangGraph nodes
│   │   │   ├── graph.py         # Graph definition
│   │   │   └── prompts.py       # Prompt templates
│   │   ├── services/
│   │   │   ├── __init__.py
│   │   │   ├── pinecone_client.py
│   │   │   ├── embeddings.py
│   │   │   ├── retrieval.py
│   │   │   ├── llm.py
│   │   │   └── chunking.py
│   │   └── api/
│   │       ├── __init__.py
│   │       ├── routes.py        # API endpoints
│   │       └── streaming_utils.py
│   ├── requirements.txt
│   └── .env.example
│
└── extension/
    ├── public/
    │   ├── manifest.json
    │   └── icons/
    ├── src/
    │   ├── background/
    │   │   └── background.ts    # Service worker
    │   ├── content/
    │   │   ├── content_script.ts
    │   │   └── extractor.ts     # Page text extraction
    │   ├── overlay/
    │   │   ├── App.tsx
    │   │   ├── index.tsx
    │   │   ├── components/
    │   │   │   ├── Header.tsx
    │   │   │   ├── StatusBar.tsx
    │   │   │   ├── Summary.tsx
    │   │   │   └── FollowUp.tsx
    │   │   └── hooks/
    │   │       └── useStreaming.ts
    │   ├── styles/
    │   │   └── tailwind.css
    │   └── types/
    │       └── index.ts
    ├── package.json
    ├── tsconfig.json
    ├── webpack.config.js
    ├── tailwind.config.js
    └── postcss.config.js
```

## Configuration

### Backend Configuration (.env)

| Variable | Description | Default |
|----------|-------------|---------|
| `PINECONE_API_KEY` | Your Pinecone API key | Required |
| `PINECONE_ENVIRONMENT` | Pinecone region | `us-east-1` |
| `PINECONE_INDEX_NAME` | Index name | `docpilot-pages` |
| `OLLAMA_BASE_URL` | Ollama server URL | `http://localhost:11434` |
| `OLLAMA_MODEL` | LLM model to use | `mistral` |
| `CHUNK_SIZE` | Tokens per chunk | `512` |
| `TOP_K_RETRIEVAL` | Results for similarity search | `5` |
| `DEBUG` | Enable debug mode | `false` |

### Supported LLM Models

- `mistral` (recommended, 7B parameters)
- `llama3:8b` (Meta's LLaMA 3)
- `llama2` (Meta's LLaMA 2)
- `codellama` (for code-heavy pages)

## Development

### Backend Development
```bash
cd backend
source venv/bin/activate
uvicorn app.main:app --reload --log-level debug
```

### Extension Development
```bash
cd extension
npm run dev  # Watches for changes and rebuilds
```

### Type Checking
```bash
# Backend
cd backend
mypy app/

# Extension
cd extension
npm run typecheck
```

## Troubleshooting

### "Model not found" error
```bash
# Pull the model first
ollama pull mistral
```

### CORS errors
- Ensure the backend is running on port 8000
- Check that CORS is enabled in FastAPI

### Extension not loading
- Check Chrome developer console for errors
- Ensure manifest.json is valid
- Verify all files are in dist/ folder

### Pinecone connection issues
- Verify API key is correct
- Check Pinecone dashboard for index status
- Ensure region matches your index

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Run tests and linting
5. Submit a pull request

## License

MIT License - see LICENSE file for details.

## Acknowledgments

- [LangGraph](https://github.com/langchain-ai/langgraph) for agent orchestration
- [Ollama](https://ollama.ai) for local LLM inference
- [Pinecone](https://pinecone.io) for vector storage
- [Sentence Transformers](https://www.sbert.net/) for embeddings
