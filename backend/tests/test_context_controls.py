import pytest
from app.llm.client import LLMClient
from app.runtime import Runtime
from app.workspace import Workspace


def test_long_history_retains_system_and_cited_sources():
    built=LLMClient()._build([{'role':'user','content':str(i)} for i in range(100)],{'documents':[{'title':'Source','content':'Private reference'}]})
    assert built[0]['role']=='system'
    assert '[1] Source' in built[0]['content']
    assert len(built)==21
    assert built[-1]['content']=='99'


@pytest.mark.asyncio
async def test_session_controls_are_independent_of_interrupted_turn(tmp_path):
    class Socket:
        events=[]
        async def send_json(self,event):self.events.append(event)
    store=Workspace(tmp_path/'db');owner,_=store.create_owner();conversation=store.conversation(owner);socket=Socket()
    runtime=Runtime(socket,store,owner,conversation['id']);runtime.turn_id='stopped'
    for kind in ('reminder','wake_detected','cleared'):
        await runtime.send(kind)
    assert all(event['turn_id'] is None for event in socket.events)
    assert [event['sequence'] for event in socket.events]==[1,2,3]
