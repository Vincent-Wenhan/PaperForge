"""Self-check for PRD V2 validator (ponytail leave-behind)."""

from __future__ import annotations

from pydantic import ValidationError

from paperforge.schemas.prd import PRD


def demo() -> None:
    base = {
        "prd_id": "prd_1",
        "product_name": "X",
        "features": [
            {"id": "f1", "name": "Upload", "priority": "must"},
            {"id": "f2", "name": "Search", "priority": "should"},
        ],
        "acceptance_criteria": [
            {
                "id": "ac1",
                "feature_id": "f1",
                "priority": "must",
                "description": "upload visible",
                "test_kind": "interaction",
                "selector": "[data-testid='up']",
                "expected": True,
            }
        ],
    }
    PRD.model_validate(base)  # must-feature f1 covered -> ok

    # must feature without criterion -> rejected
    bad = dict(base)
    bad["acceptance_criteria"] = [
        {
            "id": "ac2",
            "feature_id": "f2",
            "priority": "should",
            "description": "search",
            "test_kind": "interaction",
        }
    ]
    try:
        PRD.model_validate(bad)
    except ValidationError:
        pass
    else:
        raise AssertionError("must feature without criterion should be rejected")

    print("prd-v2 ok")


if __name__ == "__main__":
    demo()
