"""
validator.py - Code validation before execution
"""

import ast
from typing import Tuple

BLOCKED_IMPORTS = [
    "os", "sys", "subprocess", "shutil", "socket",
    "requests", "urllib", "http", "ftplib", "smtplib",
    "pickle", "marshal", "shelve"
]


def validate_code(code: str) -> Tuple[bool, str]:
    """
    Validate generated Python code before execution.

    Returns:
        (is_valid, error_message)
    """
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return False, f"Syntax error on line {e.lineno}: {e.msg}"

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                module_name = alias.name.split('.')[0]
                if module_name in BLOCKED_IMPORTS:
                    return False, f"Blocked import: {alias.name}"

        if isinstance(node, ast.ImportFrom):
            if node.module:
                module_name = node.module.split('.')[0]
                if module_name in BLOCKED_IMPORTS:
                    return False, f"Blocked import: {node.module}"

    if "pd.read_csv" not in code:
        return False, "Code must use pd.read_csv() to load data"

    if "write_html" not in code:
        return False, "Code must use fig.write_html() to save output"

    return True, ""
