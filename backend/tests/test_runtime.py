import asyncio
import base64
import pytest
from app.workspace import Workspace
from app.runtime import Runtime
from app.llm.client import LLMClient
from app.speech.processor import SpeechProcessor,clean_text


class Socket:
    def __init__(self): self.events=[]
    async def send_json(self,event):self.events.append(event)


@pytest.mark.asyncio
async def test_interrupt_isolated_and_partial_history_saved(tmp_path,monkeypatch):
    async def stream(self,*args,**kwargs):
        yield 'First token '
        await asyncio.sleep(10)
        yield 'should be cancelled'
    monkeypatch.setattr(LLMClient,'stream_response',stream)
    store=Workspace(tmp_path/'work.db');alice,_=store.create_owner();bob,_=store.create_owner()
    ca=store.conversation(alice);cb=store.conversation(bob);sa=Socket();sb=Socket()
    a=Runtime(sa,store,alice,ca['id']);b=Runtime(sb,store,bob,cb['id'])
    await a.start(text='alice private');await b.start(text='bob private')
    await asyncio.sleep(.02);await a.interrupt()
    assert not b.task.done()
    assert sa.events[-1]['type']=='interrupted'
    assert store.history(alice,ca['id'])[-1]['content']=='First token '
    assert all(m['content']!='alice private' for m in store.history(bob,cb['id']))
    await b.interrupt(False)


@pytest.mark.asyncio
async def test_audio_order_contract_and_citations(tmp_path,monkeypatch):
    async def stream(self,*args,**kwargs):
        yield 'One.'
        yield ' Two.'
    async def synthesize(self,text):
        await asyncio.sleep(.01 if text=='One.' else 0)
        return {'success':True,'audio_data':text.encode(),'format':'mp3'}
    monkeypatch.setattr(LLMClient,'stream_response',stream);monkeypatch.setattr(SpeechProcessor,'synthesize',synthesize)
    store=Workspace(tmp_path/'work.db');owner,_=store.create_owner();conversation=store.conversation(owner)
    store.save_record(owner,'document','One source','One reference with actual evidence.')
    socket=Socket();runtime=Runtime(socket,store,owner,conversation['id'])
    await runtime.start(text='One reference',speak=True);await runtime.task
    audio=[e for e in socket.events if e['type']=='audio_chunk']
    assert [base64.b64decode(e['audio_b64']).decode() for e in audio]==['One.',' Two.']
    assert [e['audio_sequence'] for e in audio]==[0,1]
    assert len({e['turn_id'] for e in socket.events})==1
    assert socket.events[-1]['type']=='stream_end'
    assert socket.events[-1]['sources'][0]['title']=='One source'
    assert store.history(owner,conversation['id'])[-1]['content']=='One. Two.'


def test_multilingual_speech_text_survives_cleaning():
    assert 'नमस्ते' in clean_text('**नमस्ते** Wednesday')
