"""Bevro integration: Locuvi as an MCP server for the owner's agent platform (roadmap step 7).

`POST /mcp` speaks the Model Context Protocol (JSON-RPC 2.0, streamable-HTTP transport with
plain JSON responses). It exposes the same controlled tools as Ask Locuvi:
- every request needs `Authorization: Bearer <token>` for a token the owner created in
  Settings › Connected agents (only a SHA-256 is stored; revocable at any time);
- tokens are read-only unless the owner allowed drafts; even then only the two draft tools
  (invoice draft without a number, email text) exist — nothing can issue, send, pay or submit;
- browser requests (an Origin header) are refused, guarding against DNS-rebinding;
- every tool call is written to the audit log with the token's name.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from typing import Any

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from locuvi import __version__, db
from locuvi.assistant import agent
from locuvi.errors import DomainError, NotFound
from locuvi.models import AgentToken, utcnow
from locuvi.services import core

PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
DRAFT_TOOLS = {"prepare_invoice_draft", "draft_email"}
INSTRUCTIONS = (
    "Locuvi is a UK GP locum's invoicing and records app. Tools read sessions, invoices, "
    "payments, pension Forms A/B and inbox documents, and (if allowed) prepare drafts for the "
    "owner to review. Figures come from Locuvi's records. Nothing can be issued, sent, paid or "
    "submitted through these tools; the owner does that in Locuvi."
)

router = APIRouter()


# ---------------------------------------------------------------------- tokens


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_token(s: Session, name: str, allow_drafts: bool) -> tuple[AgentToken, str]:
    name = (name or "").strip()[:100] or "Bevro"
    token = "lcv_" + secrets.token_urlsafe(32)
    row = AgentToken(name=name, token_hash=_hash(token), hint=token[-4:], allow_drafts=allow_drafts)
    s.add(row)
    core.audit(s, "agent_token.created", name=name, allow_drafts=allow_drafts)
    s.commit()
    return row, token


def revoke_token(s: Session, token_id: str) -> None:
    row = s.get(AgentToken, token_id)
    if row is None:
        raise NotFound("agent_token.not_found", "Token not found.")
    row.revoked_at = row.revoked_at or utcnow()
    core.audit(s, "agent_token.revoked", name=row.name)
    s.commit()


def token_public(t: AgentToken) -> dict[str, Any]:
    return {"id": t.id, "name": t.name, "hint": t.hint, "allow_drafts": t.allow_drafts,
            "created_at": t.created_at, "last_used_at": t.last_used_at,
            "revoked": t.revoked_at is not None}  # fmt: skip


def _authenticate(s: Session, request: Request) -> AgentToken | None:
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        return None
    digest = _hash(auth[7:].strip())
    row = s.scalars(select(AgentToken).where(AgentToken.token_hash == digest)).first()
    if row is None or row.revoked_at is not None or not hmac.compare_digest(row.token_hash, digest):
        return None
    return row


# ---------------------------------------------------------------------- JSON-RPC


def _ok(id_: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": id_, "result": result}


def _err(id_: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": id_, "error": {"code": code, "message": message}}


def tools_for(token: AgentToken) -> list[dict[str, Any]]:
    out = []
    for t in agent.TOOLS:
        if t["name"] in DRAFT_TOOLS and not token.allow_drafts:
            continue
        out.append({
            "name": t["name"],
            "description": t["description"],
            "inputSchema": t["input_schema"],
            "annotations": {"readOnlyHint": t["name"] not in DRAFT_TOOLS,
                            "destructiveHint": False, "openWorldHint": False},
        })  # fmt: skip
    return out


def _handle(s: Session, settings: Any, token: AgentToken, msg: dict[str, Any]) -> Any:
    method, id_ = msg.get("method"), msg.get("id")
    params = msg.get("params") or {}
    if method == "initialize":
        asked = params.get("protocolVersion")
        version = asked if asked in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0]
        return _ok(id_, {
            "protocolVersion": version,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "locuvi", "title": "Locuvi", "version": __version__},
            "instructions": INSTRUCTIONS,
        })  # fmt: skip
    if method == "ping":
        return _ok(id_, {})
    if method == "tools/list":
        return _ok(id_, {"tools": tools_for(token)})
    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        allowed = {t["name"] for t in tools_for(token)}
        if name not in allowed:
            return _err(id_, -32602, f"Unknown or not permitted tool: {name}")
        if not isinstance(args, dict):
            return _err(id_, -32602, "arguments must be an object")
        schema = next(t["input_schema"] for t in agent.TOOLS if t["name"] == name)
        missing = [k for k in schema["required"] if k not in args]
        extra = [k for k in args if k not in schema["properties"]]
        if missing or extra:
            return _err(id_, -32602, f"Invalid arguments (missing {missing}, unexpected {extra})")
        tools = agent.Tools(s, settings)
        try:
            result = tools.run(name, args)
            is_error = False
            text = json.dumps(agent._jsonable(result))[: agent.MAX_TOOL_CHARS]
        except (DomainError, ValueError, TypeError) as exc:
            s.rollback()
            is_error = True
            text = f"Error: {getattr(exc, 'message', None) or exc}"
        core.audit(s, "bevro.tool_call", token=token.name, tool=name, ok=not is_error)
        s.commit()
        return _ok(id_, {"content": [{"type": "text", "text": text}], "isError": is_error})
    if id_ is None:  # a notification we don't need (e.g. notifications/initialized)
        return None
    return _err(id_, -32601, f"Method not found: {method}")


@router.post("/mcp")
async def mcp_post(request: Request) -> Response:
    if request.headers.get("origin"):
        return JSONResponse(_err(None, -32600, "Browser requests are not accepted."), 403)
    body = await request.body()
    if len(body) > 256 * 1024:
        return JSONResponse(_err(None, -32600, "Request too large."), 413)
    from locuvi import profiles

    base = request.app.state.settings
    pid = profiles.find(base, lambda s: _authenticate(s, request) is not None)
    if pid is not None:
        db.set_profile(pid)  # the token belongs to this household profile
    settings = request.app.state.profile_settings.get(pid or 1, base)
    with db.new_session() as s:
        token = _authenticate(s, request) if pid is not None else None
        if token is None:
            return JSONResponse(
                _err(None, -32001, "Unauthorized"), 401,
                headers={"WWW-Authenticate": 'Bearer realm="locuvi"'},
            )  # fmt: skip
        token.last_used_at = utcnow()
        s.commit()
        try:
            payload = json.loads(body)
        except ValueError:
            return JSONResponse(_err(None, -32700, "Parse error"), 400)
        batch = payload if isinstance(payload, list) else [payload]
        if not batch or not all(isinstance(m, dict) and m.get("jsonrpc") == "2.0" for m in batch):
            return JSONResponse(_err(None, -32600, "Invalid request"), 400)
        replies = [r for m in batch[:20] if (r := _handle(s, settings, token, m)) is not None]
    if not replies:
        return Response(status_code=202)
    return JSONResponse(replies if isinstance(payload, list) else replies[0])


@router.get("/mcp")
async def mcp_get() -> Response:
    # No server-initiated stream: this server only answers requests.
    return Response(status_code=405, headers={"Allow": "POST"})
