from fastapi import APIRouter, HTTPException, Request

from backend.services.channels import ChannelInput

router = APIRouter(prefix="/api/channels", tags=["channels"])


@router.get("")
def list_channels(request: Request):
    store = request.app.state.channels
    return {"items": [store.public(row) for row in store.list()]}


@router.post("")
def create_channel(payload: ChannelInput, request: Request):
    try:
        return request.app.state.channels.save(payload)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.put("/{channel_id}")
def update_channel(channel_id: str, payload: ChannelInput, request: Request):
    try:
        return request.app.state.channels.save(payload, channel_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.delete("/{channel_id}")
def delete_channel(channel_id: str, request: Request):
    try:
        request.app.state.channels.delete(channel_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    return {"ok": True}


@router.post("/{channel_id}/reset")
def reset_channel(channel_id: str, request: Request):
    try:
        request.app.state.channels.reset(channel_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    return {"ok": True}
