"""Local timezone-aware calendar proposals. No invitations or provider writes."""
import hashlib
import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from zoneinfo import ZoneInfo
from fastapi import HTTPException


def instant(value):
    value = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if not value.tzinfo:
        raise ValueError('Use a date with an explicit timezone offset')
    return value.astimezone(timezone.utc)


class Planning:
    def __init__(self, store):
        self.store = store
        with store.db() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS calendar_events(owner TEXT NOT NULL,id TEXT NOT NULL,title TEXT NOT NULL,start TEXT NOT NULL,end TEXT NOT NULL,PRIMARY KEY(owner,id));
            CREATE TABLE IF NOT EXISTS calendar_proposals(owner TEXT NOT NULL,id TEXT NOT NULL,value TEXT NOT NULL,snapshot TEXT NOT NULL,applied INTEGER NOT NULL DEFAULT 0,PRIMARY KEY(owner,id));''')

    def events(self, owner):
        with self.store.db() as db:
            return [dict(r) for r in db.execute('SELECT id,title,start,end FROM calendar_events WHERE owner=? ORDER BY start', (owner,))]

    @staticmethod
    def digest(events):
        return hashlib.sha256(json.dumps(events, sort_keys=True).encode()).hexdigest()

    def import_ics(self, owner, text):
        # Recurrence is rejected rather than silently omitting busy intervals.
        lines = text.replace('\r\n ', '').replace('\r\n\t', '').splitlines()
        if len(lines) > 10000 or not lines or lines[0] != 'BEGIN:VCALENDAR':
            raise ValueError('Expected a bounded iCalendar file')
        events, current = [], None
        for line in lines:
            if line == 'BEGIN:VEVENT': current = {}
            elif line == 'END:VEVENT':
                if current is None: raise ValueError('Malformed event')
                if any(key in current for key in ('RRULE', 'RDATE', 'EXDATE', 'RECURRENCE-ID')):
                    raise ValueError('Recurring events require expansion before import')
                def date(key):
                    raw=current[key]
                    if raw.endswith('Z'):
                        return datetime.strptime(raw, '%Y%m%dT%H%M%SZ').replace(tzinfo=timezone.utc).isoformat()
                    zone=current.get(key+'_TZID')
                    if not zone: raise ValueError('Floating/all-day times need an explicit timezone')
                    local=datetime.strptime(raw,'%Y%m%dT%H%M%S')
                    z=ZoneInfo(zone)
                    aware=local.replace(tzinfo=z)
                    if aware.astimezone(timezone.utc).astimezone(z).replace(tzinfo=None)!=local:
                        raise ValueError('Nonexistent daylight-saving time')
                    if local.replace(tzinfo=z,fold=0).utcoffset()!=local.replace(tzinfo=z,fold=1).utcoffset():
                        raise ValueError('Ambiguous daylight-saving time; convert it to UTC')
                    return aware.astimezone(timezone.utc).isoformat()
                try:
                    start, end = date('DTSTART'), date('DTEND')
                    uid = current['UID']
                except (KeyError, ValueError):
                    raise ValueError('Timed events require UID, DTSTART and DTEND; convert floating, ambiguous or all-day events to UTC')
                if end <= start or len(uid) > 500: raise ValueError('Invalid event duration or UID')
                events.append((owner, uid, current.get('SUMMARY', 'Event')[:200].replace('\\n', '\n').replace('\\,', ',').replace('\\;', ';'), start, end))
                current = None
            elif current is not None and ':' in line:
                key, value = line.split(':', 1)
                if ';' in key and key.split(';')[0] in ('DTSTART', 'DTEND'):
                    base,*params=key.split(';')
                    zone=next((p[5:].strip('"') for p in params if p.startswith('TZID=')),None)
                    if not zone or len(params)!=1: raise ValueError('Convert all-day or unsupported calendar date parameters to UTC')
                    current[base+'_TZID']=zone
                    key=base
                current[key] = value
        if current is not None or not events: raise ValueError('No complete timed events found')
        with self.store.db() as db:
            db.executemany('INSERT INTO calendar_events VALUES(?,?,?,?,?) ON CONFLICT(owner,id) DO UPDATE SET title=excluded.title,start=excluded.start,end=excluded.end', events)
        return {'imported': len(events), 'google_calendar': 'Unavailable; local files only'}

    def export(self, owner):
        lines = ['BEGIN:VCALENDAR','VERSION:2.0','PRODID:-//Wednesday//Local Planner//EN']
        def escape(v): return v.replace('\\','\\\\').replace('\r','').replace('\n','\\n').replace(';','\\;').replace(',','\\,')
        for e in self.events(owner):
            lines += ['BEGIN:VEVENT','UID:'+escape(e['id']),'DTSTAMP:'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'),'DTSTART:'+instant(e['start']).strftime('%Y%m%dT%H%M%SZ'),'DTEND:'+instant(e['end']).strftime('%Y%m%dT%H%M%SZ'),'SUMMARY:'+escape(e['title']),'END:VEVENT']
        folded=[]
        for line in lines+['END:VCALENDAR']:
            chunk=''
            for character in line:
                if len((chunk+character).encode('utf-8'))>74:
                    folded.append(chunk);chunk=' '
                chunk+=character
            folded.append(chunk)
        return '\r\n'.join(folded+[''])

    def propose(self, owner, title, start, end, minutes):
        start, end = instant(start), instant(end)
        if end <= start or end-start > timedelta(days=7): raise ValueError('Choose a working window of at most seven days')
        events = self.events(owner)
        cursor = start
        for event in events:
            a,b=instant(event['start']),instant(event['end'])
            if b <= cursor: continue
            if a >= cursor+timedelta(minutes=minutes): break
            cursor=max(cursor,b)
        if cursor+timedelta(minutes=minutes)>end: raise HTTPException(409,'No free block fits this working window')
        value={'id':uuid4().hex,'title':title,'start':cursor.isoformat(),'end':(cursor+timedelta(minutes=minutes)).isoformat()}
        with self.store.db() as db:
            db.execute('INSERT INTO calendar_proposals VALUES(?,?,?,?,0)',(owner,value['id'],json.dumps(value),self.digest(events)))
        return value

    def approve(self, owner, identity):
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT * FROM calendar_proposals WHERE owner=? AND id=?',(owner,identity)).fetchone()
            if not row: raise HTTPException(404,'Proposal unavailable')
            if row['applied']: return {'status':'applied','id':identity}
            events=[dict(r) for r in db.execute('SELECT id,title,start,end FROM calendar_events WHERE owner=? ORDER BY start',(owner,))]
            if self.digest(events)!=row['snapshot']: raise HTTPException(409,'Calendar changed; create and review a new proposal')
            value=json.loads(row['value'])
            db.execute('INSERT INTO calendar_events VALUES(?,?,?,?,?)',(owner,identity,value['title'],value['start'],value['end']))
            db.execute('UPDATE calendar_proposals SET applied=1 WHERE owner=? AND id=?',(owner,identity))
        return {'status':'applied','id':identity}
