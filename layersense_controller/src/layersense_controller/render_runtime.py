from typing import Literal


def artifact_url_by_hash(content_hash: str, kind: Literal["preview", "final"]) -> str:
    return f"/artifacts/by-hash/{content_hash}/{kind}"
