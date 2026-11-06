"""Keep evidence lossless in JSON and safe at presentation/storage boundaries.

JSON escapes preserve unusual source code points, including lone surrogates that
cannot be encoded as UTF-8. Human-facing text visibly escapes characters forbidden
by XML 1.0 rather than removing them. This is a rendering policy, never an input
normalizer for identities, evidence matching, fingerprints or support verdicts.
"""

from __future__ import annotations

import json
import re

_XML_INVALID = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]")


def display_text(value):
    """Return XML 1.0/UTF-8-safe text with invalid code points visibly escaped.

    The same representation is used for CSV, diagnostics and the SQLite scalar
    scope index. Exact source values remain available in the raw JSON result.
    Valid Unicode (including supplementary characters), tabs and newlines stay.
    """
    return _XML_INVALID.sub(lambda match: f"\\u{ord(match[0]):04x}", str(value))


def json_dumps(value, **kwargs):
    """Serialize exact source values without requiring valid UTF-8 input text."""
    kwargs["ensure_ascii"] = True
    return json.dumps(value, **kwargs)
