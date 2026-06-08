"""The MCP compat shim tolerates malformed server messages (e.g. a bad `ping`)."""

from mcp import types

import dmcp._mcp_compat  # noqa: F401  (applies the lenient-parse patch on import)


def test_malformed_ping_notification_does_not_raise():
    # a `ping` sent as a notification (no id) matches no type in the union and
    # would normally raise ValidationError -> killing the explore. Now tolerated.
    msg = types.JSONRPCMessage.model_validate_json('{"method":"ping","jsonrpc":"2.0"}')
    assert msg is not None


def test_unknown_garbage_does_not_raise():
    msg = types.JSONRPCMessage.model_validate_json('{"method":"notifications/weird","jsonrpc":"2.0"}')
    assert msg is not None


def test_valid_message_still_parses_unchanged():
    msg = types.JSONRPCMessage.model_validate_json('{"jsonrpc":"2.0","id":7,"result":{"tools":[]}}')
    assert msg is not None
    # the real response is returned (not coerced to the ping fallback)
    assert getattr(msg.root, "id", None) == 7
