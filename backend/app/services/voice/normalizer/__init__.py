"""The output normalizer — text as written becomes text as spoken.

Ported from Rapida's `normalizer/output/normalizer.go`, which runs an ordered
chain of `TextNormalizer`s over each sentence on its way to the synthesiser.

**Order is the whole design.** Each stage consumes a form a later stage would
otherwise mangle, so the chain is not a set:

    markdown        strip formatting first, or `**₹50,000**` never matches the
                    currency pattern
    url             handles and links go before symbols, which would eat the @
    currency        needs the digits still as digits to attach "rupees" to
    unit            same, for km and kg
    date            before time — an ISO timestamp contains a clock, and the
                    time pass would claim it first and leave a stray date
    time
    duration        before plain numbers, or "168 hours" is already spelled out
    number          everything numeric that survived the passes above
    abbreviation    after numbers, so "SP" is not mistaken for a spelled digit
    symbol          last: whatever is left with no pronunciation

Reordering these looks harmless and produces bugs that only show up in audio,
which is why the list is a constant with the reasoning next to it rather than
something assembled at call time.

The chain is pure text in, pure text out — no I/O, no state, no async. That is
deliberate: this is the layer most likely to need a quick fix when something
sounds wrong in a demo, and it should be possible to test a fix in a REPL.
"""
from __future__ import annotations

import logging

from app.services.voice.normalizer.abbreviation import AbbreviationNormalizer
from app.services.voice.normalizer.currency import (CurrencyNormalizer,
                                                    UnitNormalizer)
from app.services.voice.normalizer.date_time import (DateNormalizer,
                                                     DurationNormalizer,
                                                     TimeNormalizer)
from app.services.voice.normalizer.number import NumberNormalizer
from app.services.voice.normalizer.symbol import (MarkdownNormalizer,
                                                  SymbolNormalizer,
                                                  UrlNormalizer,
                                                  split_identifier)
from app.services.voice.types import TextNormalizer

log = logging.getLogger("sentinel.voice.normalizer")

#: The chain, in the only order that is correct. See the module docstring.
DEFAULT_CHAIN: tuple[str, ...] = (
    "markdown", "url", "currency", "unit", "date", "time", "duration",
    "number", "abbreviation", "symbol",
)

_REGISTRY: dict[str, type] = {
    "markdown": MarkdownNormalizer,
    "url": UrlNormalizer,
    "currency": CurrencyNormalizer,
    "unit": UnitNormalizer,
    "date": DateNormalizer,
    "time": TimeNormalizer,
    "duration": DurationNormalizer,
    "number": NumberNormalizer,
    "abbreviation": AbbreviationNormalizer,
    "symbol": SymbolNormalizer,
}


class OutputNormalizer:
    """Runs the chain. One method, and it is the point of the package."""

    def __init__(self, chain: tuple[str, ...] = DEFAULT_CHAIN) -> None:
        self.normalizers: list[TextNormalizer] = []
        for name in chain:
            factory = _REGISTRY.get(name)
            if factory is None:
                log.warning("unknown normalizer %r — skipped", name)
                continue
            self.normalizers.append(factory())

    def normalize(self, text: str) -> str:
        """Text as written in, text as spoken out.

        A failing stage is logged and skipped rather than propagated. A regex
        that met input its author did not imagine should cost one imperfect
        sentence, not the officer's answer.
        """
        if not text or not text.strip():
            return ""
        for normalizer in self.normalizers:
            try:
                text = normalizer.normalize(text)
            except Exception:
                log.exception("normalizer %s failed — passing text through",
                              getattr(normalizer, "name", "?"))
        return text.strip()

    def explain(self, text: str) -> list[tuple[str, str]]:
        """Every stage's output, for working out which one broke a sentence.

        Exposed on the voice-diagnostics endpoint. When someone reports that
        the assistant mispronounced something, this turns a guess into a
        two-second answer.
        """
        trace: list[tuple[str, str]] = [("input", text)]
        for normalizer in self.normalizers:
            try:
                text = normalizer.normalize(text)
            except Exception as exc:
                trace.append((getattr(normalizer, "name", "?"), f"failed: {exc}"))
                continue
            trace.append((getattr(normalizer, "name", "?"), text))
        return trace


_default: OutputNormalizer | None = None


def default() -> OutputNormalizer:
    """The shared instance. The chain is stateless, so one is enough."""
    global _default
    if _default is None:
        _default = OutputNormalizer()
    return _default


def normalize(text: str) -> str:
    return default().normalize(text)


__all__ = ["OutputNormalizer", "DEFAULT_CHAIN", "default", "normalize",
           "split_identifier"]
