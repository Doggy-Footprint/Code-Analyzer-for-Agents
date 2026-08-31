import math
from typing import Optional

from .graph_models import NodeCost, SourceSpan

CHARACTERS_PER_TOKEN = 4.0


def estimate_tokens(text: str, characters_per_token: float = CHARACTERS_PER_TOKEN) -> int:
    return max(1, math.ceil(len(text) / characters_per_token))


def cost_for_text(text: str, characters_per_token: float = CHARACTERS_PER_TOKEN) -> NodeCost:
    return NodeCost(
        token_estimate=estimate_tokens(text, characters_per_token),
        char_count=len(text),
        line_count=text.count("\n") + 1 if text else 0,
    )


def cost_for_span(
    source: str,
    span: SourceSpan,
    characters_per_token: float = CHARACTERS_PER_TOKEN,
) -> NodeCost:
    return cost_for_text(text_for_span(source, span), characters_per_token)


def text_for_span(source: str, span: SourceSpan) -> str:
    lines = source.splitlines()
    start = max(0, span.start_line - 1)
    end = max(start, span.end_line)
    return "\n".join(lines[start:end])


def cost_for_node_lines(
    source: str,
    start_line: int,
    end_line: Optional[int],
    file_path: str = "",
    characters_per_token: float = CHARACTERS_PER_TOKEN,
) -> NodeCost:
    span = SourceSpan(file_path, start_line, end_line if end_line is not None else start_line)
    return cost_for_span(source, span, characters_per_token)
