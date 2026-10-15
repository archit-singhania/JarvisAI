import pytest
from app.continuity import Continuity
from app.workspace import Workspace


def fixture(tmp_path):
    store = Workspace(tmp_path/'continuity.db')
    owner, _ = store.create_owner()
    stranger, _ = store.create_owner()
    return store, Continuity(store), owner, stranger


def test_branch_snapshot_survives_parent_deletion_without_memories(tmp_path):
    store, service, owner, stranger = fixture(tmp_path)
    parent = store.conversation(owner)['id']
    store.message(owner, parent, 'user', 'Original question')
    mid = store.history(owner, parent)[0]['id']
    store.message(owner, parent, 'assistant', 'Later answer')
    with pytest.raises(KeyError): service.branch(stranger, parent, mid, 'Forbidden')
    with pytest.raises(KeyError): service.branch(owner, parent, mid+500, 'Invalid')
    child = service.branch(owner, parent, mid, 'Alternative')['id']
    assert len(store.history(owner, child)) == 1
    store.message(owner, child, 'user', 'Different direction')
    assert len(store.history(owner, parent)) == 2
    assert not store.records(owner, 'memory')
    store.delete_conversation(owner, parent)
    restored = Continuity(Workspace(store.path))
    snapshot = restored.provenance(owner, child)['parent']['snapshot']
    assert [m['content'] for m in snapshot] == ['Original question']
    with pytest.raises(KeyError): restored.provenance(stranger, child)


def test_layout_ownership_client_and_revision(tmp_path):
    store, service, owner, stranger = fixture(tmp_path)
    value = {'version':1,'rail':'compact','density':'focused','view':'chat','context_ids':[]}
    row = service.layout(owner,'browser','a'*32,'Focus',value,0)
    assert row['revision'] == 1
    assert service.layouts(owner,'wpf') == []
    with pytest.raises(ValueError): service.layout(owner,'browser',row['id'],'stale',value,0)
    with pytest.raises(KeyError): service.layout(stranger,'browser',row['id'],'hack',value,1)
    assert service.layout(owner,'browser',row['id'],'Focus 2',value,1)['revision']==2
    assert Continuity(Workspace(store.path)).layouts(owner,'browser')[0]['title']=='Focus 2'


def test_digest_only_explicit_sources_and_ownership(tmp_path):
    store, service, owner, stranger = fixture(tmp_path)
    selected = store.conversation(owner)['id']
    excluded = store.conversation(owner)['id']
    store.message(owner,selected,'user','Included content')
    store.message(owner,excluded,'user','PRIVATE excluded content')
    receipt = store.receipt(owner,'time',{'success':True,'content':'12:00'})
    digest = service.digest(owner,[selected],[],[receipt],'2020-01-01T00:00:00+00:00')
    assert len(digest['items'])==2 and digest['partial_coverage']
    assert 'PRIVATE' not in str(digest)
    with pytest.raises(KeyError): service.digest(stranger,[selected],[],[],'2020')
    with pytest.raises(KeyError): service.digest(stranger,[],[],[receipt],'2020')
    assert service.digests(stranger)==[]
    assert Continuity(Workspace(store.path)).digests(owner)[0]['id']==digest['id']
