from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from security.request_context import current_trusted_request


def pwa_conversation_router(runtime):
    router = APIRouter(prefix='/iphone/api/conversations', tags=['iphone-pwa-conversations'])
    continuity = runtime['continuity']

    def require_session():
        context = current_trusted_request()
        if context is None:
            raise HTTPException(401, {
                'code': 'session_expired',
                'message': 'This browser session is missing, expired, or revoked.',
            })
        return context

    @router.post('/{conversation_id}/archive')
    def archive(conversation_id: str):
        require_session()
        thread = continuity.thread(conversation_id)
        if not thread:
            raise HTTPException(404, 'Conversation not found')
        if thread.get('closed_at'):
            return {'ok': True, 'conversation_id': conversation_id, 'status': 'already_archived'}
        continuity.archive_thread(conversation_id)
        return {'ok': True, 'conversation_id': conversation_id, 'status': 'archived'}

    @router.delete('/{conversation_id}')
    def delete(conversation_id: str):
        require_session()
        if not continuity.delete_thread(conversation_id):
            raise HTTPException(404, 'Conversation not found')
        return {'ok': True, 'conversation_id': conversation_id, 'status': 'deleted'}

    @router.get('/{conversation_id}/export')
    def export(conversation_id: str):
        require_session()
        try:
            bundle = continuity.export_thread(conversation_id)
        except KeyError as exc:
            raise HTTPException(404, 'Conversation not found') from exc
        return JSONResponse(
            content=bundle,
            headers={
                'Content-Disposition': f'attachment; filename="personal-ai-conversation-{conversation_id}.json"'
            },
        )

    return router
