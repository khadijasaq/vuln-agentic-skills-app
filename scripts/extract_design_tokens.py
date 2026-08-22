"""
Pull the colours and the font out of the design reference file.

The visual design for this app is defined once, in design/aegis-design-foundations.html.
That file contains two things we need:

  1. A block of colour and spacing definitions (the "tokens").
  2. The Raleway typeface, embedded directly in the file as text.

This script copies both into the static/ folder so the app can use them. Two rules
shape how it does that:

  - The colour definitions are copied EXACTLY as written, names and values unchanged.
    Copying rather than reinterpreting means the app and the design reference can
    never quietly drift apart, and any difference is a visible difference in one file.

  - The font is saved as a real font file and served from this machine. No part of
    the app ever fetches anything from the internet, so it works with no connection
    at all - which matters for a tool that is only ever run locally.

This is a one-off build helper, not part of the running app. Run it with:

    uv run python scripts/extract_design_tokens.py
"""

from __future__ import annotations

import base64
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DESIGN_FILE = REPO_ROOT / "design" / "aegis-design-foundations.html"
# The styling lives with the rest of the frontend, which the backend serves.
TOKENS_OUTPUT = REPO_ROOT / "frontend" / "static" / "css" / "tokens.css"
FONT_OUTPUT = REPO_ROOT / "frontend" / "static" / "fonts" / "raleway.woff2"


def extract_token_block(html: str) -> str:
    """
    Find the block of colour and spacing definitions.

    In: the whole design file as text. Out: just the definitions block.

    The definitions live inside a ":root { ... }" section, which is the standard way
    of writing values that the whole page can refer to by name.
    """
    match = re.search(r":root\s*\{(.*?)\}", html, re.DOTALL)
    if not match:
        raise SystemExit("Could not find the token block in the design file.")
    return match.group(1).strip()


def extract_font(html: str) -> bytes:
    """
    Find the Raleway typeface embedded in the design file.

    In: the whole design file as text. Out: the font as real file content.

    Fonts can be embedded in a web page as a long run of text. This finds that run
    and turns it back into an ordinary font file.
    """
    match = re.search(r"url\(data:font/woff2;base64,([A-Za-z0-9+/=]+)\)", html)
    if not match:
        raise SystemExit("Could not find the embedded font in the design file.")
    return base64.b64decode(match.group(1))


def main() -> None:
    """
    Do the extraction and write both files.

    In: nothing. Out: nothing (writes to the static folder).
    """
    if not DESIGN_FILE.exists():
        raise SystemExit(f"The design reference file is missing: {DESIGN_FILE}")

    html = DESIGN_FILE.read_text(encoding="utf-8")

    tokens = extract_token_block(html)
    TOKENS_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    TOKENS_OUTPUT.write_text(
        "/*\n"
        " * Colours, spacing and type, copied EXACTLY from the design reference file\n"
        " * (design/aegis-design-foundations.html) by scripts/extract_design_tokens.py.\n"
        " *\n"
        " * Do not edit by hand. Change the design file and run the script again.\n"
        " * Nothing else in this app is allowed to write a colour value directly - every\n"
        " * colour used anywhere is one of the names defined below.\n"
        " */\n\n"
        ":root {\n" + tokens + "\n}\n",
        encoding="utf-8",
    )
    print(f"Wrote {TOKENS_OUTPUT.relative_to(REPO_ROOT)}")

    font = extract_font(html)
    FONT_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    FONT_OUTPUT.write_bytes(font)
    print(f"Wrote {FONT_OUTPUT.relative_to(REPO_ROOT)} ({len(font):,} bytes)")


if __name__ == "__main__":
    main()
