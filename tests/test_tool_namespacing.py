"""Namespaced tool names round-trip even when the server_id contains `__`."""

from dmcp.llm import namespace_tool, unnamespace_tool


def test_roundtrip_server_with_double_underscore():
    sid, tool = "io_github_expertvagabond__mega", "get_current_dir"
    assert unnamespace_tool(namespace_tool(sid, tool)) == (sid, tool)


def test_roundtrip_ausdata_style():
    sid, tool = "io_ausdata__abs_mcp", "search_datasets"
    assert unnamespace_tool(namespace_tool(sid, tool)) == (sid, tool)


def test_roundtrip_simple_server():
    sid, tool = "eurostat", "eurostat_search_datasets"
    assert unnamespace_tool(namespace_tool(sid, tool)) == (sid, tool)


def test_roundtrip_compose_single_underscore():
    sid, tool = "compose_git", "git_status"
    assert unnamespace_tool(namespace_tool(sid, tool)) == (sid, tool)
