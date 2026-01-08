"""
Main FastAPI application for Jarvis AI
"""
import logging
import logging.config
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings, LOGGING_CONFIG

# Configure logging
logging.config.dictConfig(LOGGING_CONFIG)
logger = logging.getLogger("jarvis")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle manager for startup and shutdown"""
    logger.info("🚀 Starting Jarvis AI...")
    logger.info(f"Host: {settings.HOST}:{settings.PORT}")
    logger.info(f"Debug Mode: {settings.DEBUG}")
    logger.info(f"LLM Model: {settings.LLM_MODEL}")
    
    # Initialize components here
    # await orchestrator.initialize()
    
    yield
    
    # Cleanup
    logger.info("👋 Shutting down Jarvis AI...")


# Create FastAPI app
app = FastAPI(
    title="Jarvis AI",
    description="Advanced AI Assistant with Voice, Vision, and RAG capabilities",
    version="1.0.0",
    lifespan=lifespan
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Update for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Health check endpoint
@app.get("/")
async def root():
    """Root endpoint - health check"""
    return {
        "status": "online",
        "service": "Jarvis AI",
        "version": "1.0.0"
    }


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "models": {
            "llm": settings.LLM_MODEL,
            "vision": settings.VISION_MODEL,
            "whisper": settings.WHISPER_MODEL,
            "tts": settings.TTS_MODEL
        }
    }


# WebSocket endpoint for real-time communication
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time AI interaction"""
    await websocket.accept()
    logger.info("WebSocket connection established")
    
    try:
        while True:
            # Receive message from client
            data = await websocket.receive_json()
            
            # Process the message
            message_type = data.get("type")
            
            if message_type == "audio":
                # Handle audio input
                response = {"type": "text", "content": "Audio processing not yet implemented"}
                
            elif message_type == "text":
                # Handle text input
                user_input = data.get("content")
                response = {
                    "type": "text",
                    "content": f"Echo: {user_input}"
                }
                
            elif message_type == "image":
                # Handle image input
                response = {"type": "text", "content": "Image processing not yet implemented"}
                
            else:
                response = {"type": "error", "content": "Unknown message type"}
            
            # Send response back to client
            await websocket.send_json(response)
            
    except WebSocketDisconnect:
        logger.info("WebSocket connection closed")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        await websocket.close()


# API Routes
@app.post("/api/chat")
async def chat(request: dict):
    """Text-based chat endpoint"""
    user_message = request.get("message")
    
    if not user_message:
        return JSONResponse(
            status_code=400,
            content={"error": "Message is required"}
        )
    
    # Process with orchestrator (to be implemented)
    response = f"Echo: {user_message}"
    
    return {
        "response": response,
        "type": "text"
    }


@app.post("/api/speech/transcribe")
async def transcribe_audio(request: dict):
    """Transcribe audio to text"""
    # To be implemented
    return {"transcript": "Transcription not yet implemented"}


@app.post("/api/speech/synthesize")
async def synthesize_speech(request: dict):
    """Convert text to speech"""
    # To be implemented
    return {"audio_url": "TTS not yet implemented"}


@app.post("/api/vision/analyze")
async def analyze_image(request: dict):
    """Analyze image with vision model"""
    # To be implemented
    return {"analysis": "Vision analysis not yet implemented"}


@app.post("/api/rag/query")
async def rag_query(request: dict):
    """Query the RAG system"""
    # To be implemented
    return {"answer": "RAG query not yet implemented"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG
    )