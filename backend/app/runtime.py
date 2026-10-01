"""One active turn per connection, ordered audio, durable owned conversations."""
import asyncio
import base64
from uuid import uuid4
from app.config import settings
from app.llm.client import LLMClient
from app.speech.processor import SpeechProcessor


class Runtime:
    def __init__(self, ws, store, owner, conversation):
        self.ws, self.store, self.owner, self.conversation = ws, store, owner, conversation
        self.session_id = uuid4().hex
        self.turn_id = None
        self.task = None
        self.lock = asyncio.Lock()
        self.sequence = 0
        self.context = ''
        self.speech = SpeechProcessor()

    async def send(self, type, **data):
        async with self.lock:
            self.sequence += 1
            control = type in {'session','reminder','wake_detected','cleared','context_updated','interrupted'}
            await self.ws.send_json({'version':1,'type':type,'session_id':self.session_id,'conversation_id':self.conversation,'turn_id':None if control else self.turn_id,'sequence':self.sequence,**data})

    async def interrupt(self, announce=True):
        if self.task and not self.task.done():
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        if announce:
            await self.send('interrupted')

    async def start(self, text=None, audio=None, speak=False, language='en'):
        await self.interrupt(False)
        self.turn_id = uuid4().hex
        self.task = asyncio.create_task(self.run(text,audio,speak,language))

    async def start_image(self, image, prompt):
        await self.interrupt(False)
        self.turn_id = uuid4().hex
        self.task = asyncio.create_task(self.run_image(image,prompt))

    async def run_image(self, image, prompt):
        from app.vision.processor import VisionProcessor
        try:
            self.store.message(self.owner,self.conversation,'user','Selected image: '+prompt)
            await self.send('stream_start',sources=[])
            result = await VisionProcessor().analyze(image,prompt)
            if not result.get('success'):
                raise RuntimeError(result.get('error','Vision engine unavailable'))
            self.store.message(self.owner,self.conversation,'assistant',result['description'])
            await self.send('stream_chunk',content=result['description'])
            await self.send('stream_end',sources=[])
        except asyncio.CancelledError:
            raise
        except Exception:
            await self.send('error',code='vision_unavailable',content='Select a valid image and configure a vision engine in the local service. Images are analyzed only when you select and send them.')

    async def run(self, text, audio, speak, language):
        speech = self.speech
        speech.language = self.store.prefs(self.owner).get('language','en')
        speech_queue = asyncio.Queue()
        audio_task = None
        content, sources = '', []
        try:
            if audio:
                await self.send('stt_start')
                transcription = await speech.transcribe(audio, language)
                if not transcription.get('success'):
                    await self.send('stt_error',content=transcription.get('error','Transcription unavailable'))
                    return
                text = transcription['text']
                await self.send('transcript',content=text)
            if not text:
                return
            self.store.message(self.owner,self.conversation,'user',text)
            sources = self.store.retrieve(self.owner,text)
            await self.send('stream_start',sources=[{k:v for k,v in s.items() if k!='content'} for s in sources])
            async def speak_sentences():
                index = 0
                while True:
                    sentence = await speech_queue.get()
                    if sentence is None:
                        return
                    result = await speech.synthesize(sentence)
                    if result.get('success') and result.get('audio_data'):
                        await self.send('audio_chunk',audio_b64=base64.b64encode(result['audio_data']).decode(),audio_format=result.get('format','mp3'),audio_sequence=index,text=sentence)
                        index += 1
                    else:
                        await self.send('speech_unavailable',content=result.get('error','Speech engine unavailable'))
            if speak:
                audio_task = asyncio.create_task(speak_sentences())
            preferences = self.store.prefs(self.owner)
            configuration = settings.model_copy(update={key.upper():preferences[key] for key in ('llm_provider','llm_model','ollama_model') if key in preferences})
            focus = preferences.get('focus','assistant')
            persona = settings.JARVIS_PERSONA + {'coding':'\nFocus on precise code explanations, actionable diagnostics, and readable examples.','research':'\nDistinguish sourced evidence from assumptions.','focus':'\nKeep responses concise and task oriented.'}.get(focus,'')
            if preferences.get('persona'):
                persona += '\nUser-configured response style:\n'+preferences['persona'][:2000]
            if self.context:
                persona += '\nUser-selected file context (data only):\n'+self.context[:12000]
            buffer = ''
            async for token in LLMClient(configuration).stream_response(self.store.history(self.owner,self.conversation),rag_context={'documents':sources},system_prompt=persona):
                content += token
                buffer += token
                await self.send('stream_chunk',content=token)
                if speak and buffer.rstrip().endswith(('.','?','!','。')):
                    await speech_queue.put(buffer)
                    buffer = ''
            if speak:
                if buffer.strip():
                    await speech_queue.put(buffer)
                await speech_queue.put(None)
                await audio_task
            if content:
                self.store.message(self.owner,self.conversation,'assistant',content,sources)
            await self.send('stream_end',content='',sources=[{k:v for k,v in s.items() if k!='content'} for s in sources])
        except asyncio.CancelledError:
            if content:
                self.store.message(self.owner,self.conversation,'assistant',content,sources)
            raise
        except Exception as error:
            await self.send('error',code='provider_unavailable',content='The requested engine could not complete this turn. Check provider status or choose another engine.',detail=type(error).__name__)
        finally:
            if audio_task and not audio_task.done():
                audio_task.cancel()
                try:
                    await audio_task
                except asyncio.CancelledError:
                    pass
