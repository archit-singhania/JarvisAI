"""Owned interfaces for local continuity expansion."""
import asyncio
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from urllib.parse import parse_qs, urlsplit
from secrets import compare_digest
from pydantic import BaseModel, Field, ConfigDict, model_validator
from app.offline import Offline
from app.planning import Planning
from app.watchfolders import WatchFolders
from app.evaluations import Evaluations
from app.google_calendar import GoogleCalendar
from fastapi.responses import HTMLResponse, RedirectResponse


class Strict(BaseModel):
    model_config=ConfigDict(extra='forbid')

class EditValue(Strict):
    title: str=Field(min_length=1,max_length=200)
    content: str=Field(min_length=1,max_length=20000)
    due_at: str|None=Field(default=None,max_length=60)

class Edit(Strict):
    operation_id: str=Field(pattern=r'^[a-zA-Z0-9-]{1,80}$')
    id: str=Field(pattern=r'^[a-zA-Z0-9-]{1,80}$')
    kind: Literal['draft','note','memory','reminder']
    expected_revision: int=Field(ge=0)
    value: EditValue

    @model_validator(mode='after')
    def reminder_time(self):
        if self.kind=='reminder' and not self.value.due_at:
            raise ValueError('Reminder requires a timestamp with UTC offset')
        return self

class CalendarImport(Strict):
    text: str=Field(max_length=1000000)

class Proposal(Strict):
    title: str=Field(min_length=1,max_length=200)
    start: str=Field(max_length=60)
    end: str=Field(max_length=60)
    minutes: int=Field(ge=5,le=480)

class Approval(Strict):
    confirmed: Literal[True]

class Watch(Approval):
    root: str=Field(min_length=1,max_length=1000)
    exclusions: list[str]=Field(default_factory=list,max_length=50)

class Case(Approval):
    title: str=Field(min_length=1,max_length=200)
    query: str=Field(min_length=1,max_length=2000)
    expected_sources: list[str]=Field(default_factory=list,max_length=20)
    kind: Literal['retrieval','python_diagnostics']='retrieval'
    expect_error: bool=False

    @model_validator(mode='after')
    def require_sources(self):
        if self.kind=='retrieval' and not self.expected_sources:raise ValueError('Select expected sources for a retrieval case')
        return self

class GoogleSelection(Approval):
    calendar: str=Field(min_length=1,max_length=500)


def router(get_store, owner):
    routes=APIRouter(prefix='/api/expansion',tags=['Local expansion'])
    def call(action):
        try: return action()
        except KeyError: raise HTTPException(404,'Owned resource unavailable')
        except (ValueError,TypeError) as error: raise HTTPException(422,str(error))

    @routes.get('/offline')
    def edits(identity=Depends(owner)): return {'records':Offline(get_store()).list(identity)}

    @routes.post('/offline')
    def sync(body:Edit,identity=Depends(owner)): return call(lambda:Offline(get_store()).apply(identity,body.model_dump()))

    @routes.get('/calendar')
    def calendar(identity=Depends(owner)): return {'events':Planning(get_store()).events(identity),'google':GoogleCalendar(get_store()).status(identity),'checked_until':Planning(get_store()).checked_until(identity),'import_scope':'Timed, all-day and recurring events'}

    @routes.post('/calendar/google/oauth/start')
    def google_oauth_start(request: Request, response: Response, identity=Depends(owner)):
        result = GoogleCalendar(get_store()).begin_oauth(identity)
        if get_store().authenticate(request.cookies.get('wednesday_token')) == identity:
            state = parse_qs(urlsplit(result['url']).query)['state'][0]
            response.set_cookie('wednesday_google_return',state,max_age=600,httponly=True,
                                secure=request.url.scheme=='https',samesite='lax',
                                path='/api/expansion/calendar/google/oauth/callback')
        return result

    @routes.get('/calendar/google/oauth/callback', response_class=HTMLResponse)
    def google_oauth_callback(request: Request, state: str, code: str | None = None):
        outcome = 'connected'
        try:
            connected_owner = GoogleCalendar(get_store()).finish_oauth(state,code)
        except HTTPException as error:
            if error.detail == 'Google sign-in was cancelled':
                outcome = 'cancelled'
            elif error.status_code in (403,502):
                outcome = 'incomplete'
            else:
                raise
            connected_owner = None
        try:
            browser_owner = owner(request)
        except HTTPException:
            browser_owner = None
        browser_state = request.cookies.get('wednesday_google_return','')
        if (connected_owner and browser_owner == connected_owner) or (browser_state and compare_digest(browser_state.encode(),state.encode())):
            response = RedirectResponse('/ui/?view=expansion&google='+outcome, status_code=303,
                                    headers={'Cache-Control':'no-store','Referrer-Policy':'no-referrer'})
            response.delete_cookie('wednesday_google_return',path='/api/expansion/calendar/google/oauth/callback')
            return response
        heading = {
            'connected':'Google Calendar connected',
            'cancelled':'Google sign-in cancelled',
            'incomplete':'Google Calendar sign-in could not finish',
        }[outcome]
        return HTMLResponse(f'<!doctype html><html lang="en"><title>{heading}</title><h1>{heading}</h1><p>Return to Wednesday to continue.</p></html>',headers={'Cache-Control':'no-store','Referrer-Policy':'no-referrer'})

    @routes.get('/calendar/google')
    def google_calendars(identity=Depends(owner)): return GoogleCalendar(get_store()).calendars(identity)

    @routes.post('/calendar/google/connect')
    def google_connect(body:GoogleSelection,identity=Depends(owner)): return GoogleCalendar(get_store()).connect(identity,body.calendar)

    @routes.post('/calendar/google/sync')
    def google_sync(identity=Depends(owner)): return GoogleCalendar(get_store()).sync(identity)

    @routes.delete('/calendar/google')
    def google_disconnect(identity=Depends(owner)):
        return GoogleCalendar(get_store()).disconnect(identity)

    @routes.post('/calendar/proposals/{proposal}/google')
    def google_write(proposal:str,body:Approval,identity=Depends(owner)): return GoogleCalendar(get_store()).approve(identity,proposal)

    @routes.post('/calendar/import')
    def importing(body:CalendarImport,identity=Depends(owner)): return call(lambda:Planning(get_store()).import_ics(identity,body.text))

    @routes.get('/calendar/export')
    def exporting(identity=Depends(owner)): return {'text':Planning(get_store()).export(identity)}

    @routes.post('/calendar/proposals')
    def propose(body:Proposal,identity=Depends(owner)): return call(lambda:Planning(get_store()).propose(identity,**body.model_dump()))

    @routes.post('/calendar/proposals/{proposal}/approve')
    def approve(proposal:str,body:Approval,identity=Depends(owner)): return call(lambda:Planning(get_store()).approve(identity,proposal))

    @routes.get('/folders')
    def folders(identity=Depends(owner)): return {'folders':WatchFolders(get_store()).list(identity)}

    @routes.post('/folders')
    def folder(body:Watch,identity=Depends(owner)):
        from app.config import settings
        if settings.DEMO_MODE: raise HTTPException(403,'Host folders are disabled in hosted demonstrations')
        return call(lambda:WatchFolders(get_store()).add(identity,body.root,body.exclusions))

    @routes.delete('/folders/{folder_id}')
    def remove(folder_id:str,identity=Depends(owner)):
        call(lambda:WatchFolders(get_store()).remove(identity,folder_id)); return {'removed':True}

    @routes.get('/evaluations')
    def evaluations(identity=Depends(owner)): return Evaluations(get_store()).list(identity)

    @routes.post('/evaluations')
    def save_case(body:Case,identity=Depends(owner)): return call(lambda:Evaluations(get_store()).save(identity,body.model_dump()))

    @routes.post('/evaluations/run-suite')
    def run_suite(identity=Depends(owner)):
        return call(lambda: Evaluations(get_store()).run_suite(identity))

    @routes.post('/evaluations/{case_id}/run')
    def run_case(case_id:str,identity=Depends(owner)): return call(lambda:Evaluations(get_store()).run(identity,case_id))

    @routes.delete('/evaluations/{case_id}')
    def delete_case(case_id:str,identity=Depends(owner)):
        Evaluations(get_store()).delete(identity,case_id); return {'removed':True}
    return routes


async def watch_loop(store):
    service=WatchFolders(store)
    while True:
        task=asyncio.create_task(asyncio.to_thread(service.tick))
        try: await asyncio.shield(task)
        except asyncio.CancelledError:
            await task
            raise
        await asyncio.sleep(30)
