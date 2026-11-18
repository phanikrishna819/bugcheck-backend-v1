"""
Tool schemas advertised to the model.

Unlike the Java backend these take no `workspaceRoot`: the workspace is bound
to the chat session, so the model cannot point a tool at an arbitrary path.
"""
from typing import Any

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "List files and directories under the workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative directory. Use empty string for the root."},
                    "limit": {"type": "integer", "description": "Maximum entries to return, default 200."},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a UTF-8 text file from the workspace.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "Relative file path."}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_files",
            "description": "Regex search text files in the workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "regex": {"type": "string", "description": "Java/Python-style regular expression."},
                    "limit": {"type": "integer", "description": "Maximum matches, default 100."},
                },
                "required": ["regex"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git_status",
            "description": "Run `git status --short` in the workspace.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git_diff",
            "description": "Read `git diff` output in the workspace.",
            "parameters": {
                "type": "object",
                "properties": {"baseRef": {"type": "string", "description": "Optional base ref, e.g. origin/main."}},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "Run an allowed build/test/inspection command in the workspace. Destructive and git-writing commands are blocked.",
            "parameters": {
                "type": "object",
                "properties": {"command": {"type": "string", "description": "Command line to run."}},
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "apply_patch",
            "description": "Edit a file by replacing an exact, unambiguous snippet. Requires edits enabled. Writes a .bak backup.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative file path."},
                    "oldText": {"type": "string", "description": "Exact existing text; must occur exactly once."},
                    "newText": {"type": "string", "description": "Replacement text."},
                    "createIfMissing": {"type": "boolean", "description": "Create the file when it does not exist."},
                },
                "required": ["path", "oldText", "newText"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_report",
            "description": "Write a markdown report under .github/.audit-trails in the workspace. Requires edits enabled.",
            "parameters": {
                "type": "object",
                "properties": {
                    "fileName": {"type": "string", "description": "Simple .md file name."},
                    "content": {"type": "string", "description": "Markdown content."},
                },
                "required": ["fileName", "content"],
            },
        },
    },
]
