import asyncio
import pytest
from app.runtime import Runtime
from app.workspace import Workspace
from app.vision.processor import VisionProcessor,image_type


@pytest.mark.asyncio
async def test_selected_image_cancel_remains_responsive(tmp_path,monkeypatch):
    started=asyncio.Event()
    async def analyze(self,*args):
        started.set()
        await asyncio.sleep(30)
        return {'success':True,'description':'must not arrive'}
    monkeypatch.setattr(VisionProcessor,'analyze',analyze)
    class Socket:
        events=[]
        async def send_json(self,event):self.events.append(event)
    store=Workspace(tmp_path/'db');owner,_=store.create_owner();conversation=store.conversation(owner)
    socket=Socket();runtime=Runtime(socket,store,owner,conversation['id'])
    await runtime.start_image(b'image','Explain the selected image')
    await started.wait();await asyncio.wait_for(runtime.interrupt(),.5)
    assert socket.events[-1]['type']=='interrupted'
    assert not any(e['type']=='stream_end' for e in socket.events)
    assert store.history(owner,conversation['id'])[-1]['role']=='user'


def test_image_signatures_are_explicit():
    assert image_type(b'\x89PNG\r\n\x1a\nabc')=='image/png'
    assert image_type(b'RIFFxxxxWEBPabc')=='image/webp'
    with pytest.raises(ValueError):image_type(b'not a picture')
