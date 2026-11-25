"""Local timezone-aware calendar proposals. No invitations or provider writes."""
import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from zoneinfo import ZoneInfo
from itertools import islice
from time import monotonic
from dateutil.rrule import rrulestr
from fastapi import HTTPException


def recurrence_components(text, uid):
    allowed = {'UID','DTSTAMP','DTSTART','DTEND','DURATION','SUMMARY','RRULE','RDATE','EXDATE','RECURRENCE-ID','STATUS'}
    component = None
    nested = 0
    for line in text.replace('\r\n ', '').replace('\r\n\t', '').splitlines():
        if line == 'BEGIN:VEVENT':
            component = []
            nested = 0
        elif line == 'END:VEVENT' and component is not None:
            if 'UID:'+uid in component:
                yield component
            component = None
        elif component is not None:
            if line.startswith('BEGIN:'):
                nested += 1
            elif line.startswith('END:'):
                nested = max(0, nested - 1)
            elif nested == 0 and line.split(':',1)[0].split(';',1)[0] in allowed:
                component.append(line)


def recurrence_source(text, uid):
    components = list(recurrence_components(text, uid))
    if not components:
        return None
    lines = ['BEGIN:VCALENDAR', 'VERSION:2.0']
    for component in components:
        lines.extend(['BEGIN:VEVENT', *component, 'END:VEVENT'])
    return '\r\n'.join([*lines, 'END:VCALENDAR'])


def instant(value):
    value = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if not value.tzinfo:
        raise ValueError('Use a date with an explicit timezone offset')
    return value.astimezone(timezone.utc)


def event_duration(value):
    match = re.fullmatch(r'\+?P(?:(\d{1,5})W|(?:(\d{1,5})D)?(?:T(?:(\d{1,5})H)?(?:(\d{1,5})M)?(?:(\d{1,5})S)?)?)', value)
    if not match or not any(match.groups()):
        raise ValueError('Invalid calendar duration')
    weeks, days, hours, minutes, seconds = (int(part or 0) for part in match.groups())
    duration = timedelta(weeks=weeks, days=days, hours=hours, minutes=minutes, seconds=seconds)
    if duration <= timedelta(0):
        raise ValueError('Calendar duration must be positive')
    return duration


class Planning:
    def __init__(self, store):
        self.store = store
        with store.db() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS calendar_events(owner TEXT NOT NULL,id TEXT NOT NULL,title TEXT NOT NULL,start TEXT NOT NULL,end TEXT NOT NULL,PRIMARY KEY(owner,id));
            CREATE TABLE IF NOT EXISTS calendar_series(owner TEXT NOT NULL,uid TEXT NOT NULL,event_id TEXT NOT NULL,PRIMARY KEY(owner,uid,event_id));
            CREATE TABLE IF NOT EXISTS calendar_coverage(owner TEXT NOT NULL,uid TEXT NOT NULL,checked_until TEXT NOT NULL,PRIMARY KEY(owner,uid));
            CREATE TABLE IF NOT EXISTS calendar_recurrence_sources(owner TEXT NOT NULL,uid TEXT NOT NULL,source TEXT NOT NULL,PRIMARY KEY(owner,uid));
            CREATE TABLE IF NOT EXISTS calendar_migrations(name TEXT PRIMARY KEY);
            CREATE TABLE IF NOT EXISTS calendar_all_day(owner TEXT NOT NULL,id TEXT NOT NULL,start_date TEXT NOT NULL,end_date TEXT NOT NULL,PRIMARY KEY(owner,id));
            CREATE TABLE IF NOT EXISTS calendar_proposals(owner TEXT NOT NULL,id TEXT NOT NULL,value TEXT NOT NULL,snapshot TEXT NOT NULL,applied INTEGER NOT NULL DEFAULT 0,PRIMARY KEY(owner,id));''')
            if not db.execute("SELECT 1 FROM calendar_migrations WHERE name='minimize-recurrence-sources'").fetchone():
                db.execute('BEGIN IMMEDIATE')
                migration = db.execute("INSERT OR IGNORE INTO calendar_migrations VALUES('minimize-recurrence-sources')")
                if migration.rowcount:
                    for row in db.execute('SELECT owner,uid,source FROM calendar_recurrence_sources'):
                        source = recurrence_source(row['source'], row['uid'])
                        if source is not None and source != row['source']:
                            db.execute('UPDATE calendar_recurrence_sources SET source=? WHERE owner=? AND uid=?',
                                       (source,row['owner'],row['uid']))

    def events(self, owner):
        with self.store.db() as db:
            return self._events(db, owner)

    @staticmethod
    def _events(db, owner):
        return [dict(row) for row in db.execute(
            'SELECT id,title,start,end FROM calendar_events WHERE owner=? ORDER BY start', (owner,)
        )]

    def validate_snapshot(self, owner, end, snapshot):
        with self.store.db() as db:
            db.execute('BEGIN')
            self.require_coverage(instant(end), self._checked_until(db, owner))
            return self.matches_snapshot(self._events(db, owner), snapshot)

    @staticmethod
    def digest(events):
        canonical = sorted(events, key=lambda event: (event['start'], event['id']))
        return 'v2:' + hashlib.sha256(json.dumps(canonical, sort_keys=True).encode()).hexdigest()

    @classmethod
    def matches_snapshot(cls, events, snapshot):
        if snapshot.startswith('v2:'):
            return cls.digest(events) == snapshot
        return hashlib.sha256(json.dumps(events, sort_keys=True).encode()).hexdigest() == snapshot

    def import_ics(self, owner, text, *, extend_uid=None, through=None):
        lines = text.replace('\r\n ', '').replace('\r\n\t', '').splitlines()
        if len(lines) > 10000 or not lines or lines[0] != 'BEGIN:VCALENDAR':
            raise ValueError('Expected a bounded iCalendar file')
        prior_sources = {}
        prior_coverage = {}
        cancellation = 'METHOD:CANCEL' in lines
        if extend_uid is None and any(line.startswith(('RECURRENCE-ID:', 'RECURRENCE-ID;')) for line in lines):
            updates = {}
            for line in lines:
                if line.startswith('UID:'):
                    uid = line[4:]
                    updates[uid] = list(recurrence_components(text, uid))
            combined = ['BEGIN:VCALENDAR', 'VERSION:2.0']
            for uid, components in updates.items():
                def recurrence_id(component):
                    return next((field for field in component if field.split(':',1)[0].split(';',1)[0] == 'RECURRENCE-ID'), None)
                detached = [recurrence_id(component) for component in components]
                if components and all(detached):
                    with self.store.db() as db:
                        saved = db.execute('''SELECT s.source,c.checked_until FROM calendar_recurrence_sources s
                                           LEFT JOIN calendar_coverage c ON c.owner=s.owner AND c.uid=s.uid
                                           WHERE s.owner=? AND s.uid=?''',
                                           (owner,uid)).fetchone()
                    if not saved:
                        raise ValueError('Import the recurring series before updating an individual occurrence')
                    prior_sources[uid] = saved['source']
                    if saved['checked_until']:
                        prior_coverage[uid] = instant(saved['checked_until'])
                    for component in recurrence_components(saved['source'], uid):
                        if recurrence_id(component) not in detached:
                            combined.extend(['BEGIN:VEVENT', *component, 'END:VEVENT'])
                for component in components:
                    fields = component
                    if cancellation:
                        fields = [field for field in component if not field.startswith('STATUS:')]
                        fields.append('STATUS:CANCELLED')
                    combined.extend(['BEGIN:VEVENT', *fields, 'END:VEVENT'])
            if prior_sources:
                lines = [*combined, 'END:VCALENDAR']
                text = '\r\n'.join(lines)
        events, all_day, series, current = [], [], {}, None
        overrides = {}
        coverage = {}
        cancelled_series = set()
        nested = []
        method = None
        expansion_deadline = monotonic() + 2
        for line in lines:
            if current is None and line.startswith('METHOD:'):
                method = line.split(':', 1)[1].upper()
                continue
            if current is not None and line.startswith('BEGIN:'):
                if line == 'BEGIN:VEVENT':
                    raise ValueError('Nested calendar events are invalid')
                nested.append(line.removeprefix('BEGIN:'))
                continue
            if nested:
                if line.startswith('END:'):
                    if line.removeprefix('END:') != nested.pop():
                        raise ValueError('Mismatched nested calendar component')
                continue
            if line == 'BEGIN:VEVENT': current = {}
            elif line == 'END:VEVENT':
                if current is None: raise ValueError('Malformed event')
                if 'RECURRENCE-ID' in current:
                    uid = current.get('UID')
                    params, raw = current['RECURRENCE-ID']
                    future = 'RANGE=THISANDFUTURE' in params
                    params = [param for param in params if param != 'RANGE=THISANDFUTURE']
                    if params == ['VALUE=DATE']:
                        original = datetime.strptime(raw, '%Y%m%d').replace(tzinfo=ZoneInfo(self.store.prefs(owner)['timezone']))
                    elif not params and raw.endswith('Z'):
                        original = datetime.strptime(raw, '%Y%m%dT%H%M%SZ').replace(tzinfo=timezone.utc)
                    elif len(params) == 1 and params[0].startswith('TZID='):
                        original = datetime.strptime(raw, '%Y%m%dT%H%M%S').replace(tzinfo=ZoneInfo(params[0][5:].strip('"')))
                    else:
                        raise ValueError('Unsupported recurrence override parameters')
                    override_zone = original.tzinfo
                    original = original.astimezone(timezone.utc).isoformat()
                    override = (uid, original)
                    if not uid or override in overrides:
                        raise ValueError('Missing UID or duplicate recurrence override')
                    if current.get('STATUS') == 'CANCELLED' or method == 'CANCEL':
                        overrides[override] = (None, future, override_zone)
                        current = None
                        continue
                    synthetic = 'override:'+hashlib.sha256(repr(override).encode()).hexdigest()
                    overrides[override] = (synthetic, future, override_zone)
                    current['UID'] = synthetic
                if current.get('STATUS') == 'CANCELLED' or method == 'CANCEL':
                    uid = current.get('UID', '')
                    if not uid or len(uid) > 500 or uid.startswith('google:') or uid in series:
                        raise ValueError('Invalid cancelled event UID')
                    series[uid] = []
                    cancelled_series.add(uid)
                    current = None
                    continue
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
                    uid = current['UID']
                    if 'DURATION' in current and 'DTEND' in current:
                        raise ValueError('Use either an end date or duration')
                    explicit_duration = event_duration(current['DURATION']) if 'DURATION' in current else None
                    if uid.startswith('google:'):
                        raise ValueError('Reserved event identifier')
                    if current.get('DTSTART_TYPE') == 'DATE':
                        first = datetime.strptime(current['DTSTART'], '%Y%m%d')
                        last = first + timedelta(days=1)
                        if explicit_duration is not None:
                            if explicit_duration.seconds:
                                raise ValueError('All-day durations must use whole days')
                            last = first + explicit_duration
                        if 'DTEND' in current:
                            if current.get('DTEND_TYPE') != 'DATE':
                                raise ValueError('All-day end must be a date')
                            last = datetime.strptime(current['DTEND'], '%Y%m%d')
                        if last <= first:
                            raise ValueError('All-day end is exclusive and must follow start')
                        zone = ZoneInfo(self.store.prefs(owner)['timezone'])
                        start, end = [value.replace(tzinfo=zone).astimezone(timezone.utc).isoformat()
                                      for value in (first, last)]

                    else:
                        start = date('DTSTART')
                        if explicit_duration is None:
                            end = date('DTEND')
                        else:
                            local_zone = ZoneInfo(current['DTSTART_TZID']) if current.get('DTSTART_TZID') else timezone.utc
                            end = (instant(start).astimezone(local_zone) + explicit_duration).astimezone(timezone.utc).isoformat()
                except (KeyError, ValueError):
                    raise ValueError('Timed events require UID, DTSTART and DTEND; convert floating, ambiguous or all-day events to UTC')
                if end <= start or len(uid) > 500: raise ValueError('Invalid event duration or UID')
                if uid in series:
                    raise ValueError('Duplicate event UID')
                is_all_day = current.get('DTSTART_TYPE') == 'DATE'
                start_at, end_at = instant(start), instant(end)
                if is_all_day:
                    start_at, end_at = first.replace(tzinfo=zone), last.replace(tzinfo=zone)
                elif current.get('DTSTART_TZID'):
                    event_zone = ZoneInfo(current['DTSTART_TZID'])
                    start_at = start_at.astimezone(event_zone)
                    end_at = end_at.astimezone(event_zone)
                duration = end_at - start_at
                rule = current.get('RRULE')
                occurrences = [start_at]
                if rule:
                    bounded = any(part.startswith(('COUNT=', 'UNTIL=')) for part in rule.split(';'))
                    target = through if uid == extend_uid else prior_coverage.get(uid)
                    extend_open_series = target is not None and not bounded
                    if is_all_day:
                        rule = ';'.join(part+'T235959' if part.startswith('UNTIL=') and len(part)==14 else part for part in rule.split(';'))
                        generated = (value.replace(tzinfo=zone) for value in rrulestr(rule, dtstart=first))
                    else:
                        generated = iter(rrulestr(rule, dtstart=start_at))
                    occurrences = []
                    candidates = generated if extend_open_series else islice(generated, 1001)
                    for occurrence in candidates:
                        if extend_open_series and monotonic() >= expansion_deadline:
                            raise HTTPException(422, 'Calendar recurrence coverage could not be verified within the expansion budget')
                        if target and len(occurrences) >= 1000 and occurrence.astimezone(timezone.utc) >= target:
                            coverage[uid] = occurrence.astimezone(timezone.utc).isoformat()
                            break
                        occurrences.append(occurrence)
                    if not extend_open_series and len(occurrences)>1000:
                        if bounded:
                            raise ValueError('Recurring series exceeds 1000 occurrences')
                        coverage[uid] = occurrences.pop().astimezone(timezone.utc).isoformat()
                additions = set()
                exclusions = set()
                for field, target in [('RDATE', additions), ('EXDATE', exclusions)]:
                    for params, values in current.get(field, []):
                        for raw in values.split(','):
                            if is_all_day and params == ['VALUE=DATE']:
                                value = datetime.strptime(raw, '%Y%m%d').replace(tzinfo=zone)
                            elif not is_all_day and not params and raw.endswith('Z'):
                                value = datetime.strptime(raw, '%Y%m%dT%H%M%SZ').replace(tzinfo=timezone.utc)
                            elif not is_all_day and len(params) == 1 and params[0].startswith('TZID='):
                                value = datetime.strptime(raw, '%Y%m%dT%H%M%S').replace(tzinfo=ZoneInfo(params[0][5:].strip('"')))
                            else:
                                raise ValueError('Recurrence dates must match the event type and specify a timezone for timed values')
                            target.add(value.astimezone(timezone.utc))
                if additions or exclusions:
                    occurrences = sorted(({value.astimezone(timezone.utc) for value in occurrences} | additions) - exclusions)
                    occurrences = [value.astimezone(start_at.tzinfo) for value in occurrences]
                if len(occurrences) > 1000 and not (rule and extend_open_series):
                    raise ValueError('Recurring series exceeds the occurrence limit')
                series[uid] = []
                for occurrence in occurrences:
                    occurrence_end = occurrence + duration
                    key = 'series:'+hashlib.sha256((uid+'|'+occurrence.isoformat()).encode()).hexdigest() if rule or additions or exclusions else uid
                    series[uid].append(key)
                    if is_all_day:
                        all_day.append((owner,key,occurrence.strftime('%Y%m%d'),occurrence_end.strftime('%Y%m%d')))
                    events.append((owner,key,current.get('SUMMARY','Event')[:200].replace(chr(92)+'n',chr(10)).replace(chr(92)+',',',').replace(chr(92)+';',';'),
                                   occurrence.astimezone(timezone.utc).isoformat(),
                                   occurrence_end.astimezone(timezone.utc).isoformat()))
                    if len(events)>10000 and extend_uid is None and not prior_coverage:
                        raise ValueError('Import exceeds 10000 occurrences')
                current = None
            elif current is not None and ':' in line:
                key, value = line.split(':', 1)
                base, *params = key.split(';')
                if base in ('RDATE', 'EXDATE'):
                    current.setdefault(base, []).append((params, value))
                    continue
                if base == 'RECURRENCE-ID':
                    current[base] = (params, value)
                    continue
                if ';' in key and key.split(';')[0] in ('DTSTART', 'DTEND'):
                    base,*params=key.split(';')
                    zone=next((p[5:].strip('"') for p in params if p.startswith('TZID=')),None)
                    if params == ['VALUE=DATE']:
                        current[base+'_TYPE'] = 'DATE'
                    elif zone and len(params) == 1:
                        current[base+'_TZID'] = zone
                    else:
                        raise ValueError('Unsupported calendar date parameters')
                    key=base
                current[key] = value
        by_id = {row[1]: row for row in events}
        dates_by_id = {row[1]: row for row in all_day}
        starts = {key: row[3] for key, row in by_id.items()}
        removed = set()
        ordered = sorted(overrides.items(), key=lambda item: (not item[1][1], item[0][1]))
        for (uid, original), (synthetic, future, override_zone) in ordered:
            if uid not in series:
                raise ValueError('Recurrence override needs its master event in the same file')
            if uid in cancelled_series:
                if synthetic:
                    removed.update(series.pop(synthetic))
                continue
            keys = series[uid]
            if future:
                affected = [key for key in keys if starts[key] >= original]
                if not synthetic:
                    removed.update(affected)
                    continue
                replacement_keys = series.pop(synthetic)
                if len(replacement_keys) != 1:
                    raise ValueError('Range override must contain one replacement event')
                replacement = by_id[replacement_keys[0]]
                removed.add(replacement[1])
                replacement_start = instant(replacement[3]).astimezone(override_zone)
                shift = replacement_start - instant(original).astimezone(override_zone)
                duration = instant(replacement[4]).astimezone(override_zone) - replacement_start
                if uid in coverage and shift < timedelta(0):
                    cutoff = instant(coverage[uid]).astimezone(override_zone)
                    coverage[uid] = (cutoff + shift).astimezone(timezone.utc).isoformat()
                for key in affected:
                    original_start = instant(starts[key])
                    replacement_dates = dates_by_id.get(replacement[1])
                    original_dates = dates_by_id.get(key)
                    if bool(replacement_dates) != bool(original_dates):
                        raise ValueError('Range overrides must preserve the event type')
                    if original_dates:
                        zone = ZoneInfo(self.store.prefs(owner)['timezone'])
                        original_day = instant(original).astimezone(zone).date()
                        first = datetime.strptime(replacement_dates[2], '%Y%m%d').date()
                        last = datetime.strptime(replacement_dates[3], '%Y%m%d').date()
                        delta = original_start.astimezone(zone).date() - original_day
                        first, last = first + delta, last + delta
                        start, end = (datetime.combine(day, datetime.min.time(), tzinfo=zone).astimezone(timezone.utc)
                                      for day in (first,last))
                        dates_by_id[key] = (owner,key,first.strftime('%Y%m%d'),last.strftime('%Y%m%d'))
                    else:
                        local_start = original_start.astimezone(override_zone) + shift
                        start = local_start.astimezone(timezone.utc)
                        end = (local_start + duration).astimezone(timezone.utc)
                    by_id[key] = (owner,key,replacement[2],start.isoformat(),end.isoformat())
                    removed.discard(key)
                continue
            matches = [key for key in keys if starts[key] == original]
            removed.update(matches)
            series[uid] = [key for key in keys if key not in matches]
            if synthetic:
                series[uid].extend(series.pop(synthetic))
        events = [row for key, row in by_id.items() if key not in removed]
        all_day = [row for key, row in dates_by_id.items() if key not in removed]
        series = {uid:[key for key in keys if key not in removed] for uid, keys in series.items()}
        if extend_uid is not None:
            keys = set(series[extend_uid])
            events = [row for row in events if row[1] in keys]
            all_day = [row for row in all_day if row[1] in keys]
            series = {extend_uid: series[extend_uid]}
        if current is not None or not series: raise ValueError('No complete events found')
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            for uid, keys in series.items():
                if uid in prior_sources:
                    current_source = db.execute('SELECT source FROM calendar_recurrence_sources WHERE owner=? AND uid=?',
                                                (owner,uid)).fetchone()
                    if not current_source or current_source['source'] != prior_sources[uid]:
                        raise HTTPException(409,'Recurring calendar changed during the update; retry')
                if extend_uid is not None:
                    existing = db.execute('SELECT source FROM calendar_recurrence_sources WHERE owner=? AND uid=?',(owner,uid)).fetchone()
                    if not existing or existing['source'] != text:
                        raise HTTPException(409,'Recurring calendar changed during expansion; retry')
                    previous_cutoff = db.execute(
                        'SELECT checked_until FROM calendar_coverage WHERE owner=? AND uid=?',
                        (owner, uid),
                    ).fetchone()
                    if previous_cutoff and uid in coverage and previous_cutoff['checked_until'] >= coverage[uid]:
                        return {'imported': 0, 'checked_until': self._checked_until(db, owner)}
                else:
                    db.execute('DELETE FROM calendar_recurrence_sources WHERE owner=? AND uid=?', (owner,uid))
                db.execute('DELETE FROM calendar_coverage WHERE owner=? AND uid=?', (owner, uid))
                if uid in coverage:
                    db.execute('INSERT INTO calendar_coverage VALUES(?,?,?)', (owner, uid, coverage[uid]))
                if extend_uid is None and (uid in coverage or any(key != uid for key in keys)):
                    db.execute('INSERT INTO calendar_recurrence_sources VALUES(?,?,?)',
                               (owner,uid,recurrence_source(text,uid)))
                # Replace the series as a set instead of issuing two deletes per occurrence.
                db.execute('''DELETE FROM calendar_events WHERE owner=? AND (
                    id=? OR id IN (SELECT event_id FROM calendar_series WHERE owner=? AND uid=?)
                )''',(owner,uid,owner,uid))
                db.execute('''DELETE FROM calendar_all_day WHERE owner=? AND (
                    id=? OR id IN (SELECT event_id FROM calendar_series WHERE owner=? AND uid=?)
                )''',(owner,uid,owner,uid))
                db.execute('DELETE FROM calendar_series WHERE owner=? AND uid=?',(owner,uid))
                db.executemany('INSERT INTO calendar_series VALUES(?,?,?)',[(owner,uid,key) for key in keys])
            db.executemany('INSERT INTO calendar_events VALUES(?,?,?,?,?) ON CONFLICT(owner,id) DO UPDATE SET title=excluded.title,start=excluded.start,end=excluded.end', events)
            db.executemany('DELETE FROM calendar_all_day WHERE owner=? AND id=?', [(event[0], event[1]) for event in events])
            db.executemany('INSERT INTO calendar_all_day VALUES(?,?,?,?)', all_day)
        return {'imported': len(events), 'checked_until': self.checked_until(owner)}

    def checked_until(self, owner):
        with self.store.db() as db:
            return self._checked_until(db, owner)

    @staticmethod
    def _checked_until(db, owner):
        return db.execute('SELECT MIN(checked_until) FROM calendar_coverage WHERE owner=?', (owner,)).fetchone()[0]

    @staticmethod
    def require_coverage(end, checked_until):
        if checked_until and end > instant(checked_until):
            raise HTTPException(409, 'This window exceeds the imported recurring calendar coverage')

    def export(self, owner):
        lines = ['BEGIN:VCALENDAR','VERSION:2.0','PRODID:-//Wednesday//Local Planner//EN']
        export_stamp = 'DTSTAMP:' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        def escape(v): return v.replace('\\','\\\\').replace('\r','').replace('\n','\\n').replace(';','\\;').replace(',','\\,')
        with self.store.db() as db:
            sources = db.execute('SELECT uid,source FROM calendar_recurrence_sources WHERE owner=? ORDER BY uid',(owner,)).fetchall()
            recurring_ids = {row[0] for row in db.execute('''SELECT s.event_id FROM calendar_series s
                JOIN calendar_recurrence_sources r ON r.owner=s.owner AND r.uid=s.uid WHERE s.owner=?''',(owner,))}
            events = db.execute('''SELECT e.*, a.start_date, a.end_date FROM calendar_events e
                LEFT JOIN calendar_all_day a ON a.owner=e.owner AND a.id=e.id
                WHERE e.owner=? ORDER BY e.start''', (owner,)).fetchall()
        for event in events:
            if event['id'] in recurring_ids:
                continue
            dates = []
            for key, field in [('DTSTART', 'start'), ('DTEND', 'end')]:
                if event[field+'_date']:
                    dates.append(key+';VALUE=DATE:'+event[field+'_date'])
                else:
                    dates.append(key+':'+instant(event[field]).strftime('%Y%m%dT%H%M%SZ'))
            lines += ['BEGIN:VEVENT', 'UID:'+escape(event['id']),
                      export_stamp,
                      *dates, 'SUMMARY:'+escape(event['title']), 'END:VEVENT']
        for entry in sources:
            for component in recurrence_components(entry['source'], entry['uid']):
                if not any(value.startswith('DTSTAMP:') for value in component):
                    component.append(export_stamp)
                lines.extend(['BEGIN:VEVENT',*component,'END:VEVENT'])
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
        return self._propose(owner, title, start, end, [{"title": title, "minutes": minutes}])

    def propose_tasks(self, owner, start, end, tasks):
        ordered = sorted(tasks, key=lambda task: -task["priority"])
        return self._propose(owner, "Task plan", start, end, ordered, batch=True)

    def _propose(self, owner, title, start, end, tasks, batch=False):
        start, end = instant(start), instant(end)
        if end <= start or end-start > timedelta(days=7): raise ValueError('Choose a working window of at most seven days')
        with self.store.db() as db:
            sources = db.execute('''SELECT s.uid,s.source FROM calendar_recurrence_sources s
                JOIN calendar_coverage c ON c.owner=s.owner AND c.uid=s.uid
                WHERE s.owner=? AND c.checked_until<?''',(owner,end.isoformat())).fetchall()
        for source in sources:
            self.import_ics(owner,source['source'],extend_uid=source['uid'],through=end + timedelta(days=7))
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            self.require_coverage(end, self._checked_until(db, owner))
            events = self._events(db, owner)
            occupied = [(instant(event['start']), instant(event['end'])) for event in events]
            blocks = []
            for task in tasks:
                cursor = start
                duration = timedelta(minutes=task["minutes"])
                for event_start, event_end in sorted(occupied):
                    if event_end <= cursor:
                        continue
                    if event_start >= cursor + duration:
                        break
                    cursor = max(cursor, event_end)
                if cursor + duration > end:
                    raise HTTPException(409, f"No free block fits {task['title']} in this working window")
                occupied.append((cursor, cursor + duration))
                blocks.append({'id':uuid4().hex,'title':task['title'],'start':cursor.isoformat(),'end':(cursor+duration).isoformat()})
            value = blocks[0]
            if batch:
                value = {'id':uuid4().hex,'title':title,'start':min(block['start'] for block in blocks),
                         'end':max(block['end'] for block in blocks),'blocks':blocks}
            db.execute('INSERT INTO calendar_proposals VALUES(?,?,?,?,0)',(owner,value['id'],json.dumps(value),self.digest(events)))
        return value

    def approve(self, owner, identity):
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT * FROM calendar_proposals WHERE owner=? AND id=?',(owner,identity)).fetchone()
            if not row: raise HTTPException(404,'Proposal unavailable')
            if row['applied']: return {'status':'applied','id':identity}
            value=json.loads(row['value'])
            self.require_coverage(instant(value['end']), self._checked_until(db, owner))
            events=self._events(db, owner)
            if not self.matches_snapshot(events,row['snapshot']): raise HTTPException(409,'Calendar changed; create and review a new proposal')
            for block in value.get('blocks', [value]):
                db.execute('INSERT INTO calendar_events VALUES(?,?,?,?,?)',
                           (owner,block['id'],block['title'],block['start'],block['end']))
            db.execute('UPDATE calendar_proposals SET applied=1 WHERE owner=? AND id=?',(owner,identity))
        return {'status':'applied','id':identity}
