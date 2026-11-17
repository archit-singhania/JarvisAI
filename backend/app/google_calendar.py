"""Optional owner-bound Google adapter. Secrets remain in host environment."""
import json
import os
from datetime import datetime, timezone
from urllib.parse import quote
from zoneinfo import ZoneInfo
import httpx
from fastapi import HTTPException
from app.planning import Planning


class GoogleCalendar:
    def __init__(self, store, client=None):
        self.store=store
        self.client=client
        Planning(store)
        with store.db() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS google_connections(owner TEXT PRIMARY KEY,calendar TEXT NOT NULL,sync_token TEXT,revision INTEGER NOT NULL DEFAULT 1);
            CREATE TABLE IF NOT EXISTS google_writes(owner TEXT NOT NULL,proposal TEXT NOT NULL,calendar TEXT NOT NULL,status TEXT NOT NULL,PRIMARY KEY(owner,proposal));''')

    def configured(self, owner):
        return os.environ.get('WEDNESDAY_GOOGLE_OWNER')==owner and bool(os.environ.get('WEDNESDAY_GOOGLE_ACCESS_TOKEN') or all(os.environ.get(k) for k in ('WEDNESDAY_GOOGLE_REFRESH_TOKEN','WEDNESDAY_GOOGLE_CLIENT_ID','WEDNESDAY_GOOGLE_CLIENT_SECRET')))

    def request(self, owner, method, path, **kwargs):
        if not self.configured(owner): raise HTTPException(409,'Google Calendar is not configured for this workspace')
        token=os.environ.get('WEDNESDAY_GOOGLE_ACCESS_TOKEN')
        def perform(client):
            nonlocal token
            if not token:
                response=client.post('https://oauth2.googleapis.com/token',data={'grant_type':'refresh_token','refresh_token':os.environ['WEDNESDAY_GOOGLE_REFRESH_TOKEN'],'client_id':os.environ['WEDNESDAY_GOOGLE_CLIENT_ID'],'client_secret':os.environ['WEDNESDAY_GOOGLE_CLIENT_SECRET']})
                if response.status_code!=200: raise HTTPException(409,'Google credentials need reconnection')
                token=response.json()['access_token']
            response=client.request(method,'https://www.googleapis.com/calendar/v3/'+path,headers={'Authorization':'Bearer '+token},**kwargs)
            if response.status_code not in (200,201,204,404,409,410): raise HTTPException(502,'Google Calendar request failed; check authorization and connectivity')
            return response
        if self.client: return perform(self.client)
        try:
            with httpx.Client(timeout=20,follow_redirects=False) as client: return perform(client)
        except httpx.HTTPError: raise HTTPException(502,'Google Calendar is unavailable; no completion was recorded')

    def status(self, owner):
        with self.store.db() as db: row=db.execute('SELECT calendar,revision FROM google_connections WHERE owner=?',(owner,)).fetchone()
        return {'available':self.configured(owner),'connection':dict(row) if row else None,'account_label':os.environ.get('WEDNESDAY_GOOGLE_ACCOUNT_LABEL','Configured Google account') if self.configured(owner) else None}

    def calendars(self, owner):
        response=self.request(owner,'GET','users/me/calendarList',params={'maxResults':250})
        if response.status_code!=200: raise HTTPException(502,'Calendar list unavailable')
        data=response.json()
        return {'calendars':[{'id':r['id'],'title':r.get('summary','Calendar'),'role':r.get('accessRole','reader')} for r in data.get('items',[])],'partial':bool(data.get('nextPageToken'))}

    def connect(self, owner, calendar):
        if calendar not in {r['id'] for r in self.calendars(owner)['calendars']}: raise HTTPException(422,'Choose an accessible calendar from this account')
        with self.store.db() as db:
            db.execute("DELETE FROM calendar_events WHERE owner=? AND id LIKE 'google:%'",(owner,))
            db.execute('INSERT INTO google_connections(owner,calendar) VALUES(?,?) ON CONFLICT(owner) DO UPDATE SET calendar=excluded.calendar,sync_token=NULL,revision=google_connections.revision+1',(owner,calendar))
        return self.status(owner)

    def disconnect(self, owner):
        with self.store.db() as db:
            db.execute('DELETE FROM google_connections WHERE owner=?',(owner,))
            db.execute("DELETE FROM calendar_events WHERE owner=? AND id LIKE 'google:%'",(owner,))

    def sync(self, owner):
        with self.store.db() as db: row=db.execute('SELECT * FROM google_connections WHERE owner=?',(owner,)).fetchone()
        if not row: raise HTTPException(409,'Choose a Google account/calendar first')
        token=row['sync_token']; full=not token; items=[]; page=None; reset=False
        for _ in range(50):
            params={'maxResults':1000,'singleEvents':'true'}
            if token:params['syncToken']=token
            if page:params['pageToken']=page
            response=self.request(owner,'GET','calendars/'+quote(row['calendar'],safe='')+'/events',params=params)
            if response.status_code==410 and not reset:
                token=None;page=None;full=True;reset=True;items=[];continue
            if response.status_code!=200: raise HTTPException(502,'Calendar synchronization could not finish')
            data=response.json();items.extend(data.get('items',[]));page=data.get('nextPageToken')
            if not page:break
        else: raise HTTPException(422,'Calendar exceeds the bounded synchronization budget')
        next_token=data.get('nextSyncToken')
        if not next_token: raise HTTPException(502,'Google did not return a complete synchronization checkpoint')
        events=[]
        for item in items:
            identity='google:'+item['id']
            if item.get('status')=='cancelled': events.append((identity,None));continue
            def event_time(value):
                if 'dateTime' in value:
                    from app.planning import instant
                    return instant(value['dateTime']).isoformat()
                zone=ZoneInfo(value.get('timeZone',data.get('timeZone','UTC')))
                return datetime.fromisoformat(value['date']).replace(tzinfo=zone).astimezone(timezone.utc).isoformat()
            try: start,end=event_time(item['start']),event_time(item['end'])
            except (KeyError,ValueError): raise HTTPException(422,'Unsupported calendar event; synchronization was not applied')
            events.append((identity,(item.get('summary','Busy')[:200],start,end)))
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            current=db.execute('SELECT * FROM google_connections WHERE owner=?',(owner,)).fetchone()
            if not current or current['revision']!=row['revision'] or current['calendar']!=row['calendar'] or current['sync_token']!=row['sync_token']: raise HTTPException(409,'Calendar connection changed during synchronization; retry')
            if full:db.execute("DELETE FROM calendar_events WHERE owner=? AND id LIKE 'google:%'",(owner,))
            for identity,value in events:
                if value is None:db.execute('DELETE FROM calendar_events WHERE owner=? AND id=?',(owner,identity))
                else:db.execute('INSERT INTO calendar_events VALUES(?,?,?,?,?) ON CONFLICT(owner,id) DO UPDATE SET title=excluded.title,start=excluded.start,end=excluded.end',(owner,identity,*value))
            db.execute('UPDATE google_connections SET sync_token=?,revision=revision+1 WHERE owner=?',(next_token,owner))
        return {'updated':len(events),'full_sync':full}

    def approve(self, owner, proposal):
        # Re-read provider state before a new write, then require the exact reviewed snapshot.
        self.sync(owner)
        with self.store.db() as db:
            row=db.execute('SELECT * FROM calendar_proposals WHERE owner=? AND id=?',(owner,proposal)).fetchone()
            connection=db.execute('SELECT * FROM google_connections WHERE owner=?',(owner,)).fetchone()
            receipt=db.execute('SELECT * FROM google_writes WHERE owner=? AND proposal=?',(owner,proposal)).fetchone()
        if not row or not connection: raise HTTPException(404,'Proposal or selected calendar unavailable')
        if receipt and receipt['calendar']!=connection['calendar']: raise HTTPException(409,'Proposal belongs to another calendar')
        if receipt and receipt['status']=='completed':return {'status':'completed','id':proposal}
        value=json.loads(row['value']);path='calendars/'+quote(connection['calendar'],safe='')+'/events'
        # Recover a write whose HTTP response was lost using its deterministic Google event ID.
        recovered=None
        if receipt:
            recovered=self.request(owner,'GET',path+'/'+proposal)
            if recovered.status_code==404:recovered=None
        if recovered is None and Planning.digest(Planning(self.store).events(owner))!=row['snapshot']:
            raise HTTPException(409,'Calendar changed; inspect any pending Google event before reviewing a new proposal')
        if not receipt:
            if row['applied']: raise HTTPException(409,'Already applied locally; create a fresh Google proposal')
            if Planning.digest(Planning(self.store).events(owner))!=row['snapshot']: raise HTTPException(409,'Calendar changed; create and review a fresh proposal')
            with self.store.db() as db:db.execute("INSERT INTO google_writes VALUES(?,?,?,'pending')",(owner,proposal,connection['calendar']))
        payload={'id':proposal,'summary':value['title'],'start':{'dateTime':value['start']},'end':{'dateTime':value['end']},'extendedProperties':{'private':{'wednesdayProposal':proposal}}}
        response=recovered or self.request(owner,'POST',path,params={'sendUpdates':'none'},json=payload)
        if response.status_code==409:
            response=self.request(owner,'GET',path+'/'+proposal)
        if recovered is not None or response.status_code==200:
            from app.planning import instant
            existing=response.json()
            if existing.get('extendedProperties',{}).get('private',{}).get('wednesdayProposal')!=proposal or instant(existing.get('start',{}).get('dateTime',''))!=instant(value['start']) or instant(existing.get('end',{}).get('dateTime',''))!=instant(value['end']): raise HTTPException(409,'Existing event differs; inspect Google Calendar before retrying')
        if response.status_code not in (200,201):raise HTTPException(502,'Google write incomplete; retry only after review')
        with self.store.db() as db:
            db.execute("UPDATE google_writes SET status='completed' WHERE owner=? AND proposal=?",(owner,proposal))
            db.execute('UPDATE calendar_proposals SET applied=1 WHERE owner=? AND id=?',(owner,proposal))
        return {'status':'completed','id':proposal}
