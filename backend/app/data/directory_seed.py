"""Seed fictional directory records; no face enrollment or matching."""
import json
from pathlib import Path

from sqlmodel import Session

from app.models.demo_directory import DemoDirectoryProfile

FIXTURE_DIR = Path(__file__).parent / "directory_demo"


def seed_demo_directory(session: Session) -> int:
    profiles = json.loads((FIXTURE_DIR / "profiles.json").read_text())["profiles"]
    sources = {s["id"]: s for s in json.loads((FIXTURE_DIR / "sources.json").read_text())["sources"]}
    cases = json.loads((FIXTURE_DIR / "case_histories.json").read_text())["histories"]
    added = 0
    for profile in profiles:
        if session.get(DemoDirectoryProfile, profile["id"]) is not None:
            continue
        source = sources[profile["image_source_id"]]
        session.add(DemoDirectoryProfile(
            id=profile["id"], full_name=profile["full_name"],
            role=profile["role"], bio=profile["bio"],
            image_alt=profile["image_alt"], image_source=source["source"],
            image_prompt=source["prompt"],
            image_png=(FIXTURE_DIR / profile["image_path"]).read_bytes(),
            case_history=cases[profile["id"]],
        ))
        added += 1
    session.commit()
    return added


if __name__ == "__main__":
    from app.database import init_db, session_scope

    init_db()
    with session_scope() as session:
        print(f"Added {seed_demo_directory(session)} fictional directory profiles.")
