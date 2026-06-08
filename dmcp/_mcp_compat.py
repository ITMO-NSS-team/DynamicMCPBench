"""Tolerate non-compliant MCP server messages so one flaky server can't kill a run.

Some MCP servers emit malformed control messages — most commonly a `ping` sent as
a notification (no `id`), which doesn't match any type in the SDK's JSONRPCMessage
union. The stdio reader catches the resulting ValidationError but then *pushes the
exception object into the session read-stream* (`read_stream_writer.send(exc)`);
the ClientSession receives it and re-raises, tearing down the whole exploration of
that server.

We make `JSONRPCMessage.model_validate_json` lenient: on any unparseable incoming
message we return a harmless `ping` request the client safely ignores, instead of
raising. Valid messages are untouched. Importing this module applies the patch
(idempotent); `dmcp.recorder` imports it before any MCP session opens.
"""

from __future__ import annotations

import logging

from mcp import types

log = logging.getLogger(__name__)

# A well-formed message that the client treats as a no-op ping request.
_HARMLESS = '{"jsonrpc":"2.0","id":0,"method":"ping"}'

_orig_validate = types.JSONRPCMessage.model_validate_json


def _lenient_validate_json(data, *args, **kwargs):
    try:
        return _orig_validate(data, *args, **kwargs)
    except Exception:
        snippet = data[:160] if isinstance(data, (str, bytes)) else data
        log.debug("tolerating unparseable MCP message from server: %r", snippet)
        return _orig_validate(_HARMLESS, *args, **kwargs)


def apply() -> None:
    if getattr(types.JSONRPCMessage.model_validate_json, "__name__", "") != "_lenient_validate_json":
        types.JSONRPCMessage.model_validate_json = _lenient_validate_json


apply()
