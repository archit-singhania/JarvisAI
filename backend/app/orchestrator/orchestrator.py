"""
Main Orchestrator - Coordinates all AI components
"""
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime

from app.config import settings

logger = logging.getLogger("jarvis.orchestrator")


class Orchestrator:
    """
    Central orchestrator that coordinates between:
    - Speech (STT/TTS)
    - LLM (Azure OpenAI)
    - Vision
    - RAG
    - Tools
    """
    
    def __init__(self):
        self.conversation_history: List[Dict[str, str]] = []
        self.context: Dict[str, Any] = {}
        
        # Components will be initialized lazily
        self._llm_client = None
        self._speech_processor = None
        self._vision_processor = None
        self._rag_engine = None
        self._tool_manager = None
        
        logger.info("Orchestrator initialized")
    
    @property
    def llm_client(self):
        """Lazy load LLM client"""
        if self._llm_client is None:
            from app.llm.client import LLMClient
            self._llm_client = LLMClient()
        return self._llm_client
    
    @property
    def speech_processor(self):
        """Lazy load speech processor"""
        if self._speech_processor is None:
            from app.speech.processor import SpeechProcessor
            self._speech_processor = SpeechProcessor()
        return self._speech_processor
    
    @property
    def vision_processor(self):
        """Lazy load vision processor"""
        if self._vision_processor is None:
            from app.vision.processor import VisionProcessor
            self._vision_processor = VisionProcessor()
        return self._vision_processor
    
    @property
    def rag_engine(self):
        """Lazy load RAG engine"""
        if self._rag_engine is None:
            from app.rag.engine import RAGEngine
            self._rag_engine = RAGEngine()
        return self._rag_engine
    
    @property
    def tool_manager(self):
        """Lazy load tool manager"""
        if self._tool_manager is None:
            from app.tools.manager import ToolManager
            self._tool_manager = ToolManager()
        return self._tool_manager
    
    async def process_text_input(
        self,
        user_input: str,
        use_rag: bool = False,
        use_tools: bool = True
    ) -> Dict[str, Any]:
        """
        Process text input from user
        
        Args:
            user_input: User's text input
            use_rag: Whether to use RAG for context
            use_tools: Whether to allow tool usage
            
        Returns:
            Response dictionary with text and metadata
        """
        try:
            logger.info(f"Processing text input: {user_input[:50]}...")
            
            # Add to conversation history
            self.conversation_history.append({
                "role": "user",
                "content": user_input,
                "timestamp": datetime.now().isoformat()
            })
            
            # Trim history to max context
            if len(self.conversation_history) > settings.MAX_CONTEXT_MESSAGES * 2:
                self.conversation_history = self.conversation_history[-(settings.MAX_CONTEXT_MESSAGES * 2):]
            
            # Get RAG context if enabled
            rag_context = None
            if use_rag:
                rag_context = await self.rag_engine.query(user_input)
                logger.info(f"RAG context retrieved: {len(rag_context.get('documents', []))} documents")
            
            # Detect if tools are needed
            tool_results = None
            if use_tools:
                tool_results = await self._execute_tools_if_needed(user_input)
            
            # Generate response with LLM
            response = await self.llm_client.generate_response(
                messages=self.conversation_history,
                rag_context=rag_context,
                tool_results=tool_results
            )
            
            # Add assistant response to history
            self.conversation_history.append({
                "role": "assistant",
                "content": response["content"],
                "timestamp": datetime.now().isoformat()
            })
            
            return {
                "success": True,
                "response": response["content"],
                "type": "text",
                "rag_used": use_rag,
                "tools_used": tool_results is not None,
                "metadata": {
                    "model": response.get("model"),
                    "tokens": response.get("tokens"),
                    "timestamp": datetime.now().isoformat()
                }
            }
            
        except Exception as e:
            logger.error(f"Error processing text input: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "type": "error"
            }
    
    async def process_audio_input(
        self,
        audio_data: bytes,
        use_rag: bool = False,
        use_tools: bool = True
    ) -> Dict[str, Any]:
        """
        Process audio input (speech-to-text, then process as text)
        
        Args:
            audio_data: Raw audio bytes
            use_rag: Whether to use RAG
            use_tools: Whether to allow tools
            
        Returns:
            Response with text and audio output
        """
        try:
            logger.info("Processing audio input...")
            
            # Transcribe audio to text
            transcription = await self.speech_processor.transcribe(audio_data)
            
            if not transcription.get("success"):
                return {
                    "success": False,
                    "error": "Failed to transcribe audio",
                    "type": "error"
                }
            
            user_text = transcription["text"]
            logger.info(f"Transcribed: {user_text}")
            
            # Process as text
            text_response = await self.process_text_input(
                user_input=user_text,
                use_rag=use_rag,
                use_tools=use_tools
            )
            
            if not text_response.get("success"):
                return text_response
            
            # Synthesize speech response
            audio_response = await self.speech_processor.synthesize(
                text=text_response["response"]
            )
            
            return {
                "success": True,
                "transcript": user_text,
                "response": text_response["response"],
                "audio": audio_response.get("audio_data"),
                "type": "audio",
                "metadata": text_response.get("metadata")
            }
            
        except Exception as e:
            logger.error(f"Error processing audio input: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "type": "error"
            }
    
    async def process_image_input(
        self,
        image_data: bytes,
        prompt: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Process image input with vision model
        
        Args:
            image_data: Raw image bytes
            prompt: Optional prompt for vision model
            
        Returns:
            Vision analysis response
        """
        try:
            logger.info("Processing image input...")
            
            # Analyze image
            analysis = await self.vision_processor.analyze(
                image_data=image_data,
                prompt=prompt or "Describe this image in detail."
            )
            
            if not analysis.get("success"):
                return {
                    "success": False,
                    "error": "Failed to analyze image",
                    "type": "error"
                }
            
            # Add to conversation context
            vision_result = analysis["description"]
            self.conversation_history.append({
                "role": "user",
                "content": f"[Image analyzed: {vision_result}]",
                "timestamp": datetime.now().isoformat()
            })
            
            return {
                "success": True,
                "analysis": vision_result,
                "type": "vision",
                "metadata": analysis.get("metadata")
            }
            
        except Exception as e:
            logger.error(f"Error processing image input: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "type": "error"
            }
    
    async def _execute_tools_if_needed(self, user_input: str) -> Optional[Dict[str, Any]]:
        """
        Determine if tools are needed and execute them
        
        Args:
            user_input: User's input text
            
        Returns:
            Tool execution results or None
        """
        try:
            # Simple keyword detection for now
            # TODO: Use LLM to determine tool usage
            keywords = {
                "weather": ["weather", "temperature", "forecast"],
                "time": ["time", "date", "what time"],
                "search": ["search", "look up", "find information"],
                "calculator": ["calculate", "math", "compute"]
            }
            
            user_lower = user_input.lower()
            
            for tool_name, tool_keywords in keywords.items():
                if any(keyword in user_lower for keyword in tool_keywords):
                    logger.info(f"Tool detected: {tool_name}")
                    result = await self.tool_manager.execute(tool_name, user_input)
                    return result
            
            return None
            
        except Exception as e:
            logger.error(f"Error executing tools: {e}", exc_info=True)
            return None
    
    def clear_history(self):
        """Clear conversation history"""
        self.conversation_history = []
        logger.info("Conversation history cleared")
    
    def get_history(self) -> List[Dict[str, str]]:
        """Get conversation history"""
        return self.conversation_history


# Global orchestrator instance
orchestrator = Orchestrator()