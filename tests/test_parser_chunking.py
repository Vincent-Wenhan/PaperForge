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
                "card": {
                    "paper_id": "paper",
                    "title": "Reduced",
                    "method": "Method A",
                    "metrics": [{"name": "B", "value": "1"}],
                    "evidence": [{"field": "method", "page": 1, "quote": "Method A"}],
                },
                "contract": {
                    "name": "Paper",
                    "description": "Method A",
                    "integration_mode": "mock",
                    "confidence": 0.8,
                },
            },
        ]
    )

    result = await paper_parser.parse_paper(str(pdf_path), "paper", llm)

    assert result["paper_id"] == "paper"
    assert result["title"] == "Reduced"
    # 2 maps fold straight through (no group-reduce needed), so the third call
    # is the final synthesis of card + contract.
    assert len(llm.calls) == 3
    assert any("[[Page 1]]" in message.content for message in llm.calls[0])
    assert any("[[Page 2]]" in message.content for message in llm.calls[1])
    assert any(
        "Reduce the following summaries" in (message.content or "")
        for message in llm.calls[2]
    )
    # CapabilityContract now flows to the Planner via capability_contract.
    assert result["capability_contract"]["integration_mode"] == "mock"

    # ParseCoverage is attached so truncated content is never silently dropped.
    coverage = result["parse_coverage"]
    assert coverage["total_pages"] == 2
    assert coverage["processed_pages"] == [1, 2]
    assert coverage["omitted_pages"] == []
    assert coverage["complete"] is True


def test_parse_coverage_marks_omitted_pages_when_truncated():
    coverage = paper_parser._build_parse_coverage(
        pages=["[[Page 1]]\na", "[[Page 2]]\nb", "[[Page 3]]\nc"],
        chunks=["[[Page 1]]\na", "[[Page 2]]\nb"],
    ).model_dump()
    assert coverage["total_pages"] == 3
    assert coverage["processed_pages"] == [1, 2]
    assert coverage["omitted_pages"] == [3]
    assert coverage["complete"] is False


@pytest.mark.asyncio
async def test_hierarchical_reduce_folds_groups_level_by_level():
    class CountingLLM:
        def __init__(self, summaries: list[dict]):
            self.summaries = list(summaries)
            self.calls = 0

        async def chat(self, model, messages, **kwargs):
            self.calls += 1
            return ChatResponse(
                content=json.dumps(self.summaries.pop(0)),
                finish_reason="stop",
            )

    # 13 maps in one level: >6 triggers one group step (three groups:
    # 6+6+1), leaving 3 summaries which are <=6 so synthesis happens on those.
    maps = [{"chunk": i, "data": {"title": f"M{i}"}} for i in range(1, 14)]
    llm = CountingLLM(
        [
            {"title": "G1"},  # group 1 (maps 1-6)
            {"title": "G2"},  # group 2 (maps 7-12)
            {"title": "G3"},  # group 3 (map 13)
        ]
    )

    summaries = await paper_parser._hierarchical_reduce(
        mapped=maps, llm=llm, prompt="p", paper_id="paper"
    )
    assert [s["title"] for s in summaries] == ["G1", "G2", "G3"]
