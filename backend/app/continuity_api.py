"""Narrow versioned interfaces shared by browser and desktop clients."""
from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from app.continuity import Continuity


class BranchInput(BaseModel):
    message_id: int = Field(gt=0)
    title: str = Field(min_length=1, max_length=100)


class LayoutValue(BaseModel):
    version: Literal[1] = 1
    view: Literal['chat', 'knowledge', 'memory', 'reminders', 'tools', 'continuity'] = 'chat'
    rail: Literal['expanded', 'compact'] = 'expanded'
    density: Literal['comfortable', 'focused'] = 'comfortable'
    context_ids: list[str] = Field(default_factory=list, max_length=20)


class LayoutInput(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex, pattern=r'^[a-f0-9]{32}$')
    revision: int = Field(default=0, ge=0)
    title: str = Field(min_length=1, max_length=100)
    value: LayoutValue


class DigestInput(BaseModel):
    conversation_ids: list[str] = Field(default_factory=list, max_length=30)
    reminder_ids: list[str] = Field(default_factory=list, max_length=100)
    receipt_ids: list[str] = Field(default_factory=list, max_length=100)
    since: datetime

    @field_validator('since')
    @classmethod
    def aware(cls, value):
        if value.tzinfo is None:
            raise ValueError('Use a timezone-aware date')
        return value.astimezone(timezone.utc)


class ScheduleInput(BaseModel):
    enabled: bool = False
    period: Literal['daily','weekly'] = 'daily'
    timezone: str = Field(default='UTC',max_length=100)
    hour: int = Field(default=9,ge=0,le=23)
    minute: int = Field(default=0,ge=0,le=59)
    weekday: int = Field(default=0,ge=0,le=6)
    conversation_ids: list[str] = Field(default_factory=list,max_length=30)
    reminder_ids: list[str] = Field(default_factory=list,max_length=100)
    receipt_ids: list[str] = Field(default_factory=list,max_length=100)
    @field_validator('timezone')
    @classmethod
    def zone(cls,value):
        try:ZoneInfo(value)
        except (ValueError,ZoneInfoNotFoundError):raise ValueError('Choose an IANA timezone')
        return value


def router(get_store, owner):
    routes = APIRouter(prefix='/api/continuity', tags=['Continuity'])

    def service():
        return Continuity(get_store())

    @routes.post('/conversations/{conversation}/branches')
    def branch(conversation: str, body: BranchInput, identity=Depends(owner)):
        return service().branch(identity, conversation, body.message_id, body.title)

    @routes.get('/conversations/{conversation}/branches')
    def branches(conversation: str, identity=Depends(owner)):
        return service().provenance(identity, conversation)

    @routes.get('/layouts/{client}')
    def layouts(client: Literal['browser', 'wpf', 'aurascript2'], identity=Depends(owner)):
        return {'layouts': service().layouts(identity, client)}

    @routes.post('/layouts/{client}')
    def save_layout(client: Literal['browser', 'wpf', 'aurascript2'], body: LayoutInput, identity=Depends(owner)):
        store = get_store()
        for context in body.value.context_ids:
            store.conversation(identity, context)
        try:
            return service().layout(identity, client, body.id, body.title, body.value.model_dump(), body.revision)
        except ValueError as error:
            raise HTTPException(409, str(error))

    @routes.post('/digests')
    def digest(body: DigestInput, identity=Depends(owner)):
        return service().digest(identity, list(dict.fromkeys(body.conversation_ids)),
                                list(dict.fromkeys(body.reminder_ids)), list(dict.fromkeys(body.receipt_ids)),
                                body.since.isoformat())

    @routes.get('/digests')
    def digests(identity=Depends(owner)):
        return {'digests': service().digests(identity)}

    @routes.get('/digest-schedule')
    def schedule(identity=Depends(owner)):return {'schedule':service().schedule(identity)}

    @routes.put('/digest-schedule')
    def save_schedule(body:ScheduleInput,identity=Depends(owner)):
        return {'schedule':service().schedule(identity,body.model_dump())}

    return routes
