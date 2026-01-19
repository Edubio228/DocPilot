"""
FastAPI Main Application
Entry point for the DocPilot backend server.
Configures CORS, routes, and application lifecycle.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .api import router

# Configure logging
logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager.
    Handles startup and shutdown events.
    """
    # Startup
    logger.info("Starting DocPilot backend...")
    
    # Pre-load expensive services
    try:
        from .services import get_embedding_service, get_llm_service
        
        logger.info("Loading embedding model...")
        _ = get_embedding_service()
        
        logger.info("Initializing LLM service...")
        llm = get_llm_service()
        
        # Check if LLM API is available
        if await llm.check_api_available():
            logger.info(f"Groq API available with model '{settings.groq_model}'")
        else:
            logger.warning(
                f"Groq API not reachable. Check your GROQ_API_KEY in .env"
            )
        
        logger.info("DocPilot backend ready!")
        
    except Exception as e:
        logger.error(f"Startup error: {e}")
        raise
    
    yield  # Application runs here
    
    # Shutdown
    logger.info("Shutting down DocPilot backend...")


# Create FastAPI application
app = FastAPI(
    title=settings.app_name,
    description="AI-powered page summarization backend with real-time streaming",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.debug else None,
    redoc_url="/redoc" if settings.debug else None,
)

# Configure CORS for browser extension
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Chrome extensions need wildcard
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

# Include API routes
app.include_router(router)


# Root endpoint
@app.get("/")
async def root():
    """Root endpoint returning basic API info."""
    return {
        "name": settings.app_name,
        "version": "1.0.0",
        "status": "running",
        "docs": "/docs" if settings.debug else "disabled"
    }


# Error handlers
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """Global exception handler for unhandled errors."""
    logger.error(f"Unhandled error: {exc}", exc_info=True)
    return {
        "error": "Internal server error",
        "detail": str(exc) if settings.debug else "An error occurred"
    }


if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.debug,
        log_level="debug" if settings.debug else "info"
    )
