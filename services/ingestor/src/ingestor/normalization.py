"""Parity with the pinned backend normalizeQuery/tokenize implementation."""

import re

# ECMAScript WhiteSpace + LineTerminator differs from Python str.strip()/\s.
_JS_WHITESPACE = (
    "\u0009\u000a\u000b\u000c\u000d\u0020\u00a0\u1680"
    "\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a"
    "\u2028\u2029\u202f\u205f\u3000\ufeff"
)
_REMOVED = str.maketrans("", "", "'\"׳״ּ")
_PERIODS = re.compile(r"(?<![0-9])\.|\.(?![0-9])")
_SEPARATORS = re.compile("[" + re.escape(_JS_WHITESPACE) + r",\-]+")


def normalize_name(value: str) -> str:
    return value.strip(_JS_WHITESPACE).lower()


def tokenize(value: str) -> tuple[str, ...]:
    text = value.lower().translate(_REMOVED)
    text = _PERIODS.sub(" ", text)
    return tuple(token for token in _SEPARATORS.split(text) if token)
