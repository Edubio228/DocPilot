"""
DocPilot Backend Runner Script
Convenience script to start the backend server with proper settings.
"""

import os
import sys

# Add the backend directory to the path
backend_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, backend_dir)

if __name__ == "__main__":
    import uvicorn
    from app.config import settings
    
    print(f"""
    ╔══════════════════════════════════════════════════════════════╗
    ║                   DocPilot Backend Server                     ║
    ╠══════════════════════════════════════════════════════════════╣
    ║  Starting server on http://localhost:8000                     ║
    ║  API docs available at http://localhost:8000/docs             ║
    ║                                                               ║
    ║  Make sure Ollama is running:                                 ║
    ║    ollama serve                                               ║
    ║    ollama pull {settings.ollama_model:<20}                   ║
    ╚══════════════════════════════════════════════════════════════╝
    """)
    
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.debug,
        log_level="debug" if settings.debug else "info"
    )
