"""
A helper for the tests that inspect the source code itself.

Several checks in this project work by READING the app's code rather than running
it - for example, "no file in app/skills/ imports app/findings/", or "the honest
skill never opens a file". Those checks guard structural rules that cannot be
verified by behaviour alone.

The catch is that this project comments heavily, in plain English, about the very
things those checks look for. A file explaining "this skill never imports os" would
fail a naive search for the words "import os" - not because the code does it, but
because the explanation mentions it.

This helper strips away the prose - both `#` comments and the triple-quoted
descriptions at the top of files, classes and functions - and hands back only the
lines that actually run.
"""

from __future__ import annotations

import ast
from pathlib import Path


def executable_source(path: Path) -> str:
    """
    Read a Python file and return only the code that actually runs.

    In: the file. Out: its source with comments and descriptions removed.

    How it works: Python can parse a file into a structured form, and rebuilding the
    file from that structure naturally leaves comments behind. We additionally remove
    the description text at the top of the file and of each class and function, since
    those are prose too.
    """
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))

    holders = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
    for node in ast.walk(tree):
        if not isinstance(node, holders):
            continue
        body = getattr(node, "body", [])
        if not body:
            continue
        first = body[0]
        # A description is simply a piece of text sitting on its own as the first
        # thing inside a file, class or function.
        is_description = (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        )
        if is_description:
            body.pop(0)

    return ast.unparse(tree)


def imported_modules(path: Path) -> set[str]:
    """
    Every module a Python file imports.

    In: the file. Out: the top-level module names it brings in.

    More precise than searching the text, because it cannot be fooled by the words
    appearing inside a comment or a description.
    """
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))

    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module.split(".")[0])
    return modules


def called_function_names(path: Path) -> set[str]:
    """
    Every plain function name a Python file calls.

    In: the file. Out: the names called directly, such as "open" or "print".

    Used to check that a skill never calls something it is not supposed to, without
    being confused by the same word appearing in an explanation.
    """
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))

    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            names.add(node.func.id)
    return names
