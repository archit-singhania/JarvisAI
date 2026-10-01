"""Cancellable analysis of explicitly supplied images; no automatic captures."""
import base64
from typing import Optional
import httpx
from app.config import settings


def image_type(data: bytes) -> str:
    if data.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'image/png'
    if data.startswith(b'\xff\xd8\xff'):
        return 'image/jpeg'
    if data.startswith(b'RIFF') and data[8:12] == b'WEBP':
        return 'image/webp'
    raise ValueError('Unsupported image signature')


class VisionProcessor:
    async def analyze(self, image_data: bytes, prompt: Optional[str] = None) -> dict:
        mime = image_type(image_data)
        encoded = base64.b64encode(image_data).decode()
        prompt = prompt or 'Describe this selected image, including legible text.'
        async with httpx.AsyncClient(timeout=120) as client:
            if settings.VISION_PROVIDER == 'ollama':
                response = await client.post(settings.OLLAMA_HOST.rstrip('/')+'/api/chat',json={
                    'model':settings.OLLAMA_VISION_MODEL,'stream':False,
                    'messages':[{'role':'user','content':prompt,'images':[encoded]}]})
                response.raise_for_status()
                description = response.json()['message']['content']
                provider = 'ollama'
            elif settings.VISION_PROVIDER == 'openai' and settings.OPENAI_API_KEY:
                response = await client.post('https://api.openai.com/v1/chat/completions',headers={
                    'Authorization':'Bearer '+settings.OPENAI_API_KEY},json={
                    'model':settings.VISION_MODEL,'max_tokens':1000,
                    'messages':[{'role':'user','content':[{'type':'text','text':prompt},
                        {'type':'image_url','image_url':{'url':f'data:{mime};base64,{encoded}'}}]}]})
                response.raise_for_status()
                description = response.json()['choices'][0]['message']['content']
                provider = 'openai'
            else:
                return {'success':False,'error':'Configure the selected vision provider.'}
        return {'success':bool(description),'description':description,'provider':provider}
