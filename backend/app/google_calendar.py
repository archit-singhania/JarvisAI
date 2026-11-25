"""Optional owner-bound Google adapter. Secrets remain in host environment."""
import json
import os
import hashlib
import secrets
import time
from datetime import datetime, timezone
from urllib.parse import quote, urlencode
from zoneinfo import ZoneInfo
import httpx
from fastapi import HTTPException
from cryptography.fernet import Fernet, InvalidToken
from app.planning import Planning

GOOGLE_CALENDAR_SCOPES = (
    'https://www.googleapis.com/auth/calendar.calendarlist.readonly',
    'https://www.googleapis.com/auth/calendar.events',
)


class GoogleCalendar:
    def __init__(self, store, client=None):
        self.store=store
        self.client=client
        Planning(store)
        with store.db() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS google_connections(owner TEXT PRIMARY KEY,calendar TEXT NOT NULL,sync_token TEXT,revision INTEGER NOT NULL DEFAULT 1);
            CREATE TABLE IF NOT EXISTS google_writes(owner TEXT NOT NULL,proposal TEXT NOT NULL,calendar TEXT NOT NULL,status TEXT NOT NULL,PRIMARY KEY(owner,proposal));
            CREATE TABLE IF NOT EXISTS google_oauth_states(state_hash TEXT PRIMARY KEY,owner TEXT NOT NULL UNIQUE,expires REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS google_oauth_credentials(owner TEXT PRIMARY KEY,refresh_token TEXT NOT NULL);''')

    @staticmethod
    def oauth_settings():
        keys = ('CLIENT_ID', 'CLIENT_SECRET', 'REDIRECT_URI')
        return [os.environ.get('WEDNESDAY_GOOGLE_'+key) for key in keys]

    def begin_oauth(self, owner):
        client_id, secret, redirect = self.oauth_settings()
        if not all((client_id, secret, redirect)):
            raise HTTPException(409, 'Configure the Google OAuth application first')
        self.credential_cipher()
        state = secrets.token_urlsafe(32)
        with self.store.db() as db:
            db.execute('DELETE FROM google_oauth_states WHERE owner=? OR ABS(expires)<?', (owner,time.time()))
            db.execute('INSERT INTO google_oauth_states VALUES(?,?,?)',
                       (hashlib.sha256(state.encode()).hexdigest(),owner,time.time()+600))
        params = dict(client_id=client_id,redirect_uri=redirect,response_type='code',state=state,
                      access_type='offline',prompt='consent select_account',
                      scope=' '.join(GOOGLE_CALENDAR_SCOPES))
        return {'url':'https://accounts.google.com/o/oauth2/v2/auth?'+urlencode(params)}

    def finish_oauth(self, state, code):
        client_id, secret, redirect = self.oauth_settings()
        if not all((client_id, secret, redirect)):
            raise HTTPException(409, 'Google OAuth configuration unavailable')
        cipher = self.credential_cipher()
        state_hash = hashlib.sha256(state.encode()).hexdigest()
        with self.store.db() as db:
            # A negative expiry marks a claimed state while keeping it cancellable.
            row = db.execute('UPDATE google_oauth_states SET expires=-expires WHERE state_hash=? AND expires>=? RETURNING owner',
                             (state_hash,time.time())).fetchone()
        if not row:
            raise HTTPException(400, 'Google sign-in expired or was already used')
        if not code:
            raise HTTPException(400, 'Google sign-in was cancelled')
        try:
            post = self.client.post if self.client else httpx.post
            response = post('https://oauth2.googleapis.com/token',timeout=20,
                            data=dict(code=code,client_id=client_id,client_secret=secret,
                                      redirect_uri=redirect,grant_type='authorization_code'))
            grant = response.json() if response.is_success else {}
            refresh = grant.get('refresh_token') if isinstance(grant, dict) else None
        except (ValueError,httpx.HTTPError):
            refresh = None
        if not isinstance(refresh, str) or not refresh:
            raise HTTPException(502, 'Google did not grant offline calendar access')
        granted_scopes = grant.get('scope')
        if granted_scopes is not None and (
            not isinstance(granted_scopes, str)
            or not set(GOOGLE_CALENDAR_SCOPES).issubset(granted_scopes.split())
        ):
            raise HTTPException(403, 'Google granted only part of the requested calendar access. Start sign-in again to grant both permissions.')
        owner = row['owner']
        with self.store.db() as db:
            active = db.execute('DELETE FROM google_oauth_states WHERE state_hash=? AND owner=? AND expires<=? RETURNING owner',
                                (state_hash,owner,-time.time())).fetchone()
            if not active:
                raise HTTPException(409, 'Google sign-in was cancelled or replaced')
            encrypted = 'fernet:' + cipher.encrypt((owner + ':' + refresh).encode()).decode()
            db.execute('INSERT OR REPLACE INTO google_oauth_credentials VALUES(?,?)',(owner,encrypted))
            db.execute('DELETE FROM google_connections WHERE owner=?',(owner,))
            db.execute("DELETE FROM calendar_events WHERE owner=? AND id LIKE 'google:%'",(owner,))
        return owner

    @staticmethod
    def credential_cipher():
        try:
            return Fernet(os.environ.get('WEDNESDAY_GOOGLE_CREDENTIAL_KEY','').encode())
        except ValueError:
            raise HTTPException(409, 'Configure the Google Calendar credential encryption key') from None

    def refresh_token(self, owner):
        with self.store.db() as db:
            row = db.execute('SELECT refresh_token FROM google_oauth_credentials WHERE owner=?',(owner,)).fetchone()
        if row:
            value = row['refresh_token']
            cipher = self.credential_cipher()
            if not value.startswith('fernet:'):
                with self.store.db() as db:
                    encrypted = 'fernet:' + cipher.encrypt((owner + ':' + value).encode()).decode()
                    db.execute('UPDATE google_oauth_credentials SET refresh_token=? WHERE owner=? AND refresh_token=?',
                               (encrypted, owner, value))
                return value
            try:
                bound_owner, token = cipher.decrypt(value[7:].encode()).decode().split(':',1)
                if bound_owner != owner:
                    raise InvalidToken
                return token
            except (InvalidToken, ValueError):
                raise HTTPException(409, 'Google credentials need reconnection') from None
        if os.environ.get('WEDNESDAY_GOOGLE_OWNER') == owner:
            return os.environ.get('WEDNESDAY_GOOGLE_REFRESH_TOKEN')

    def configured(self, owner):
        return bool((os.environ.get('WEDNESDAY_GOOGLE_OWNER')==owner and os.environ.get('WEDNESDAY_GOOGLE_ACCESS_TOKEN'))
                    or (all(self.oauth_settings()[:2]) and self.refresh_token(owner)))

    def request(self, owner, method, path, **kwargs):
        if not self.configured(owner): raise HTTPException(409,'Google Calendar is not configured for this workspace')
        refresh = self.refresh_token(owner)
        token = os.environ.get('WEDNESDAY_GOOGLE_ACCESS_TOKEN') if not refresh and os.environ.get('WEDNESDAY_GOOGLE_OWNER')==owner else None
        def perform(client):
            nonlocal token
            if not token:
                response=client.post('https://oauth2.googleapis.com/token',data={'grant_type':'refresh_token','refresh_token':refresh,'client_id':os.environ['WEDNESDAY_GOOGLE_CLIENT_ID'],'client_secret':os.environ['WEDNESDAY_GOOGLE_CLIENT_SECRET']})
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
        try:
            available = self.configured(owner)
        except HTTPException as error:
            if error.status_code != 409:
                raise
            available = False
        return {'available':available,'connection':dict(row) if row else None,'account_label':os.environ.get('WEDNESDAY_GOOGLE_ACCOUNT_LABEL','Configured Google account') if available else None}

    def calendars(self, owner):
        calendars = {}
        params = {'maxResults':250}
        seen_tokens = set()
        for _ in range(50):
            response = self.request(owner,'GET','users/me/calendarList',params=params)
            if response.status_code != 200:
                raise HTTPException(502,'Calendar list unavailable')
            data = response.json()
            for item in data.get('items', []):
                calendars[item['id']] = {
                    'id':item['id'], 'title':item.get('summary','Calendar'),
                    'role':item.get('accessRole','reader'),
                }
            token = data.get('nextPageToken')
            if not token:
                return {'calendars':list(calendars.values()),'partial':False}
            if token in seen_tokens:
                raise HTTPException(502,'Google returned a repeated calendar page')
            seen_tokens.add(token)
            params['pageToken'] = token
        raise HTTPException(502,'Google calendar list exceeds the supported page limit')

    def connect(self, owner, calendar):
        if calendar not in {r['id'] for r in self.calendars(owner)['calendars']}: raise HTTPException(422,'Choose an accessible calendar from this account')
        with self.store.db() as db:
            db.execute("DELETE FROM calendar_events WHERE owner=? AND id LIKE 'google:%'",(owner,))
            db.execute('INSERT INTO google_connections(owner,calendar) VALUES(?,?) ON CONFLICT(owner) DO UPDATE SET calendar=excluded.calendar,sync_token=NULL,revision=google_connections.revision+1',(owner,calendar))
        return self.status(owner)

    def disconnect(self, owner):
        with self.store.db() as db:
            row = db.execute('DELETE FROM google_oauth_credentials WHERE owner=? RETURNING refresh_token',(owner,)).fetchone()
            db.execute('DELETE FROM google_oauth_states WHERE owner=?',(owner,))
            db.execute('DELETE FROM google_connections WHERE owner=?',(owner,))
            db.execute("DELETE FROM calendar_events WHERE owner=? AND id LIKE 'google:%'",(owner,))
        if not row:
            return {'disconnected':True,'google_revocation':'not_applicable'}
        try:
            token = row['refresh_token']
            if token.startswith('fernet:'):
                bound_owner, token = self.credential_cipher().decrypt(token[7:].encode()).decode().split(':',1)
                if bound_owner != owner:
                    raise InvalidToken
            post = self.client.post if self.client else httpx.post
            response = post('https://oauth2.googleapis.com/revoke', data={'token':token}, timeout=10)
            revoked = response.is_success
        except (HTTPException, InvalidToken, ValueError, httpx.HTTPError):
            revoked = False
        return {'disconnected':True,'google_revocation':'revoked' if revoked else 'unconfirmed'}

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
        value=json.loads(row['value'])
        if 'blocks' in value:
            raise HTTPException(422,'Task plans are approved on the local calendar')
        path='calendars/'+quote(connection['calendar'],safe='')+'/events'
        # Recover a write whose HTTP response was lost using its deterministic Google event ID.
        recovered=None
        if receipt:
            recovered=self.request(owner,'GET',path+'/'+proposal)
            if recovered.status_code==404:recovered=None
        if recovered is None:
            planner = Planning(self.store)
            if not planner.validate_snapshot(owner, value['end'], row['snapshot']):
                raise HTTPException(409,'Calendar changed; inspect any pending Google event before reviewing a new proposal')
        if not receipt:
            if row['applied']: raise HTTPException(409,'Already applied locally; create a fresh Google proposal')
            with self.store.db() as db:
                db.execute("INSERT INTO google_writes VALUES(?,?,?,'pending') ON CONFLICT DO NOTHING",
                           (owner,proposal,connection['calendar']))
                pending = db.execute('SELECT calendar,status FROM google_writes WHERE owner=? AND proposal=?',
                                     (owner,proposal)).fetchone()
            if pending['calendar'] != connection['calendar']:
                raise HTTPException(409,'Proposal belongs to another calendar')
            if pending['status'] == 'completed':
                return {'status':'completed','id':proposal}
        payload={'id':proposal,'summary':value['title'],'start':{'dateTime':value['start']},'end':{'dateTime':value['end']},'extendedProperties':{'private':{'wednesdayProposal':proposal}}}
        response=recovered or self.request(owner,'POST',path,params={'sendUpdates':'none'},json=payload)
        if response.status_code==409:
            response=self.request(owner,'GET',path+'/'+proposal)
        if recovered is not None or response.status_code==200:
            from app.planning import instant
            existing=response.json()
            try:
                matches = (
                    existing.get('status') != 'cancelled'
                    and existing.get('summary') == value['title']
                    and existing.get('extendedProperties',{}).get('private',{}).get('wednesdayProposal') == proposal
                    and instant(existing.get('start',{}).get('dateTime','')) == instant(value['start'])
                    and instant(existing.get('end',{}).get('dateTime','')) == instant(value['end'])
                )
            except (AttributeError, TypeError, ValueError, OverflowError):
                matches = False
            if not matches:
                raise HTTPException(409,'Existing event differs; inspect Google Calendar before retrying')
        if response.status_code not in (200,201):raise HTTPException(502,'Google write incomplete; retry only after review')
        with self.store.db() as db:
            db.execute("UPDATE google_writes SET status='completed' WHERE owner=? AND proposal=?",(owner,proposal))
            db.execute('UPDATE calendar_proposals SET applied=1 WHERE owner=? AND id=?',(owner,proposal))
        return {'status':'completed','id':proposal}
