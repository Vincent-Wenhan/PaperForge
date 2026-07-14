from __future__ import annotations

import json
from pathlib import Path

import pytest

from paperforge.agents import paper_parser
from paperforge.llm.base import ChatResponse, Message


class ScriptedLLM:
    def __init__(self, responses: list[dict]):
        self.responses = list(responses)
        self.calls: list[list[Message]] = []

    async def chat(self, model, messages, **kwargs):
        self.calls.append(messages)
        return ChatResponse(
            content=json.dumps(self.responses.pop(0)),
            finish_reason="stop",
        )


def test_chunk_pdf_pages_preserves_pages_and_bounds():
    pages = [
        "[[Page 1]]\\n" + ("a" * 80),
        "[[Page 2]]\\n" + ("b" * 80),
    ]

    chunks = paper_parser.chunk_pdf_pages(pages, max_chars=100)

    assert len(chunks) >= 2
    assert all(len(chunk) <= 100 for chunk in chunks)
    assert "[[Page 1]]" in "".join(chunks)
    assert "[[Page 2]]" in "".join(chunks)


@pytest.mark.asyncio
async def test_parse_paper_uses_map_reduce_over_page_chunks(monkeypatch, tmp_path: Path):
    pdf_path = tmp_path / "paper.pdf"
    pdf_path.write_bytes(b"pdf")
    pages = ["[[Page 1]]\\nMethod A", "[[Page 2]]\\nMetric B"]
    monkeypatch.setattr(paper_parser, "extract_pdf_pages", lambda _: pages)
    monkeypatch.setattr(paper_parser, "MAX_CHUNK_CHARS", 24)

    llm = ScriptedLLM(
        [
            {"title": "Mapped", "method": "Method A"},
            {"title": "Mapped", "metrics": [{"name": "B", "value": "1"}]},
            {
                "paper_id": "paper",
                "title": "Reduced",
                "method": "Method A",
                "metrics": [{"name": "B", "value": "1"}],
                "evidence": [{"field": "method", "page": 1, "quote": "Method A"}],
            },
        ]
    )

    result = await paper_parser.parse_paper(str(pdf_path), "paper", llm)

    assert result["paper_id"] == "paper"
    assert result["title"] == "Reduced"
    assert len(llm.calls) == 3
    assert any("[[Page 1]]" in message.content for message in llm.calls[0])
    assert any("[[Page 2]]" in message.content for message in llm.calls[1])
    assert any("Mapped" in (message.content or "") for message in llm.calls[2])
