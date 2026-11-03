"""编辑器 Preview v1 会话控制，受理内存输入及有界临时文件，不等待图执行。"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from starlette.concurrency import run_in_threadpool

from backend.contracts.workflows.preview_session import PreviewSessionCreate, PreviewSessionRunCreate
from backend.service.api.deps.auth import AuthenticatedPrincipal, require_scopes
from backend.service.api.rest.v1.routes.workflow_runtime_support.services import ensure_project_visible
from backend.service.application.workflows.preview.session import PreviewSessionError

preview_sessions_router = APIRouter(prefix="/workflows/preview-sessions", tags=["workflows"])
Writer = Annotated[AuthenticatedPrincipal, Depends(require_scopes("workflows:write"))]


def _manager(request):
    """取得 API 进程唯一的会话管理器。"""
    return request.app.state.workflow_preview_sessions


def _session(request, session_id, principal):
    """每个控制操作重新检查 owner 和项目权限。"""
    try:
        return _manager(request).authorize(session_id, principal.principal_id, principal.project_ids)
    except PreviewSessionError as error:
        raise HTTPException(error.status, detail={"code": error.code}) from error


@preview_sessions_router.post("", status_code=201)
def create_session(body: PreviewSessionCreate, request: Request, principal: Writer):
    """创建空会话，客户端随后连接 WS 才能提交。"""
    ensure_project_visible(principal=principal, project_id=body.project_id)
    try:
        return _manager(request).create(principal_id=principal.principal_id, **body.model_dump())
    except PreviewSessionError as error:
        raise HTTPException(error.status, detail={"code": error.code}) from error


@preview_sessions_router.post("/{session_id}/runs", status_code=202)
def submit_run(session_id: str, body: PreviewSessionRunCreate, request: Request, principal: Writer):
    """固定当前 v1 文档；不接受其他应用身份或指向磁盘的执行快照。"""
    session = _session(request, session_id, principal)
    if body.application.application_id != session.application_id:
        raise HTTPException(409, detail={"code": "preview_document_identity_invalid"})
    manager = _manager(request)
    try:
        return manager.submit(session_id, principal.principal_id, body.model_dump(mode="json"), manager.pool.submit)
    except PreviewSessionError as error:
        raise HTTPException(error.status, detail={"code": error.code}) from error


@preview_sessions_router.post("/{session_id}/runs/{run_id}/cancel", status_code=202)
def cancel_run(session_id: str, run_id: str, request: Request, principal: Writer):
    """只请求取消，实际终态由进程监督确认后发送。"""
    session = _session(request, session_id, principal)
    if not session.run or session.run["run_id"] != run_id:
        raise HTTPException(404, detail={"code": "preview_run_unavailable"})
    _manager(request).pool.cancel(run_id)
    return {"run_id": run_id, "cancel_requested": True}


@preview_sessions_router.delete("/{session_id}", status_code=204)
def release_session(session_id: str, request: Request, principal: Writer):
    """幂等撤销访问；活跃 Worker 持有的借用由监督器在退出后归还。"""
    _manager(request).release(session_id, principal.principal_id)
    return Response(status_code=204)


@preview_sessions_router.post("/{session_id}/inputs/file", status_code=201)
async def upload_file(
    session_id: str, request: Request, principal: Writer,
    byte_length: Annotated[int, Query(gt=0, le=1_000_000_000)],
    file_name: Annotated[str, Query(min_length=1, max_length=255)],
):
    """流式文件输入，先准入磁盘配额；正文不经过 multipart 或整块 bytes。"""
    from backend.contracts.workflows.preview_session import PREVIEW_CHUNK_SIZE
    from backend.service.application.workflows.preview.buffers import PreviewMemoryError
    from backend.service.application.errors import ServiceError

    _session(request, session_id, principal)
    buffers = _manager(request).buffers
    media_type = request.headers.get("content-type", "application/octet-stream")
    if len(media_type) > 128:
        raise ServiceError("文件媒体类型声明过长", code="preview_input_media_type_invalid", status_code=400)
    blob = None
    committed = False
    try:
        blob = await run_in_threadpool(buffers.allocate_file, session_id, byte_length,
                                      media_type=media_type, file_name=file_name)
        index = 0
        async for chunk in request.stream():
            for start in range(0, len(chunk), PREVIEW_CHUNK_SIZE):
                with memoryview(chunk)[start:start + PREVIEW_CHUNK_SIZE] as block:
                    await run_in_threadpool(buffers.write_chunk, session_id, blob, index, block)
                index += 1
        result = await run_in_threadpool(buffers.commit, session_id, blob)
        committed = True
        return {"input_id": result["blob_id"], **result}
    except PreviewMemoryError as error:
        status = 503 if str(error) == "preview_file_policy_unconfigured" else 413
        raise ServiceError(str(error), code=str(error), status_code=status) from error
    finally:
        if blob is not None and not committed:
            buffers.release(session_id, blob)
