"""
LLM Client supporting multiple FREE providers
"""
import logging
from typing import List, Dict, Optional, Any
from groq import Groq
import google.generativeai as genai

from app.config import settings

logger = logging.getLogger("jarvis.llm")


class LLMClient:
    """Multi-provider LLM client supporting FREE services"""
    
    def __init__(self):
        self.provider = settings.LLM_PROVIDER
        self._groq_client = None
        self._gemini_model = None
        
        logger.info(f"LLM Client initialized with provider: {self.provider}")
    
    @property
    def groq_client(self):
        """Lazy load Groq client"""
        if self._groq_client is None:
            if not settings.GROQ_API_KEY:
                raise ValueError("GROQ_API_KEY not set in environment")
            self._groq_client = Groq(api_key=settings.GROQ_API_KEY)
            logger.info("Groq client initialized")
        return self._groq_client
    
    @property
    def gemini_model(self):
        """Lazy load Gemini model"""
        if self._gemini_model is None:
            if not settings.GEMINI_API_KEY:
                raise ValueError("GEMINI_API_KEY not set in environment")
            genai.configure(api_key=settings.GEMINI_API_KEY)
            self._gemini_model = genai.GenerativeModel(settings.LLM_MODEL or 'gemini-1.5-flash')
            logger.info("Gemini model initialized")
        return self._gemini_model
    
    async def generate_response(
        self,
        messages: List[Dict[str, str]],
        rag_context: Optional[Dict[str, Any]] = None,
        tool_results: Optional[Dict[str, Any]] = None,
        system_prompt: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Generate response using configured LLM provider
        
        Args:
            messages: Conversation history
            rag_context: Context from RAG system
            tool_results: Results from tool execution
            system_prompt: Optional system prompt override
            
        Returns:
            Response dictionary with content and metadata
        """
        try:
            # Build enhanced prompt with context
            enhanced_messages = self._build_enhanced_messages(
                messages, rag_context, tool_results, system_prompt
            )
            
            # Route to appropriate provider
            if self.provider == "groq":
                return await self._generate_groq(enhanced_messages)
            elif self.provider == "gemini":
                return await self._generate_gemini(enhanced_messages)
            elif self.provider == "ollama":
                return await self._generate_ollama(enhanced_messages)
            else:
                raise ValueError(f"Unsupported provider: {self.provider}")
                
        except Exception as e:
            logger.error(f"Error generating response: {e}", exc_info=True)
            return {
                "content": "I apologize, but I encountered an error processing your request.",
                "error": str(e),
                "model": self.provider
            }
    
    def _build_enhanced_messages(
        self,
        messages: List[Dict[str, str]],
        rag_context: Optional[Dict[str, Any]],
        tool_results: Optional[Dict[str, Any]],
        system_prompt: Optional[str]
    ) -> List[Dict[str, str]]:
        """Build enhanced message list with context"""
        
        # Default system prompt
        default_system = """You are Jarvis, an advanced AI assistant inspired by Tony Stark's AI.
You are helpful, intelligent, and have a touch of wit. You can:
- Answer questions accurately
- Help with tasks and provide guidance
- Use tools when needed
- Analyze images and documents
- Have natural conversations

Be concise but thorough. Show personality but stay professional."""
        
        system_message = system_prompt or default_system
        
        # Add RAG context if available
        if rag_context and rag_context.get("documents"):
            context_text = "\n\n".join([
                doc.get("content", "") for doc in rag_context["documents"][:3]
            ])
            system_message += f"\n\nRelevant context:\n{context_text}"
        
        # Add tool results if available
        if tool_results:
            system_message += f"\n\nTool results:\n{tool_results}"
        
        # Build message list
        enhanced = [{"role": "system", "content": system_message}]
        
        # Add conversation history (convert to simple format)
        for msg in messages:
            if msg.get("role") in ["user", "assistant"]:
                enhanced.append({
                    "role": msg["role"],
                    "content": msg["content"]
                })
        
        return enhanced
    
    async def _generate_groq(self, messages: List[Dict[str, str]]) -> Dict[str, Any]:
        """Generate response using Groq (FREE & Fast)"""
        try:
            logger.info(f"Generating response with Groq: {settings.LLM_MODEL}")
            
            response = self.groq_client.chat.completions.create(
                model=settings.LLM_MODEL,
                messages=messages,
                temperature=settings.TEMPERATURE,
                max_tokens=settings.MAX_TOKENS,
                stream=False
            )
            
            return {
                "content": response.choices[0].message.content,
                "model": settings.LLM_MODEL,
                "tokens": {
                    "prompt": response.usage.prompt_tokens,
                    "completion": response.usage.completion_tokens,
                    "total": response.usage.total_tokens
                },
                "provider": "groq"
            }
            
        except Exception as e:
            logger.error(f"Groq API error: {e}")
            raise
    
    async def _generate_gemini(self, messages: List[Dict[str, str]]) -> Dict[str, Any]:
        """Generate response using Gemini (FREE)"""
        try:
            logger.info(f"Generating response with Gemini: {settings.LLM_MODEL}")
            
            # Convert messages to Gemini format
            history = []
            prompt = ""
            
            for msg in messages:
                if msg["role"] == "system":
                    # Prepend system message to first user message
                    prompt = msg["content"] + "\n\n"
                elif msg["role"] == "user":
                    if history:
                        history.append({"role": "user", "parts": [msg["content"]]})
                    else:
                        prompt += msg["content"]
                elif msg["role"] == "assistant":
                    history.append({"role": "model", "parts": [msg["content"]]})
            
            # Start chat with history
            chat = self.gemini_model.start_chat(history=history[:-1] if history else [])
            
            # Generate response
            response = chat.send_message(
                prompt if not history else messages[-1]["content"],
                generation_config={
                    "temperature": settings.TEMPERATURE,
                    "max_output_tokens": settings.MAX_TOKENS,
                }
            )
            
            return {
                "content": response.text,
                "model": settings.LLM_MODEL,
                "provider": "gemini"
            }
            
        except Exception as e:
            logger.error(f"Gemini API error: {e}")
            raise
    
    async def _generate_ollama(self, messages: List[Dict[str, str]]) -> Dict[str, Any]:
        """Generate response using Ollama (FREE Local)"""
        try:
            import ollama
            
            logger.info(f"Generating response with Ollama: {settings.OLLAMA_MODEL}")
            
            response = ollama.chat(
                model=settings.OLLAMA_MODEL,
                messages=messages
            )
            
            return {
                "content": response['message']['content'],
                "model": settings.OLLAMA_MODEL,
                "provider": "ollama"
            }
            
        except Exception as e:
            logger.error(f"Ollama error: {e}")
            raise
    
    async def stream_response(
        self,
        messages: List[Dict[str, str]],
        rag_context: Optional[Dict[str, Any]] = None
    ):
        """Stream response for real-time output (for future WebSocket use)"""
        # TODO: Implement streaming
        pass