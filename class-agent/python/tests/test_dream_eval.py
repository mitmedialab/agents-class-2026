"""Evaluation comparisons must remove the intended context without leaking labels."""

import json
from pathlib import Path

import pytest

from course_server.dream_eval import prepare_packets, summarize, write_packets


def test_ablations_share_sources_and_remove_only_intended_context() -> None:
    packets, key = prepare_packets(repeats=1)
    assert len(packets) == len(key) == 6
    lookup = {p["packet_id"]: p for p in packets}
    first_context = packets[0]["context"]
    assert isinstance(first_context, dict)
    course = first_context["course_sources"]
    for meta in key:
        packet = lookup[meta["packet_id"]]
        context = packet["context"]
        assert isinstance(context, dict)
        assert context["course_sources"] == course
        assert "condition" not in packet
        assert ("student_focus" in context) == (meta["condition"] != "generic")
        assert ("feedback" in context) == (meta["condition"] == "profile_and_memory")
        if meta["condition"] == "profile_and_memory":
            assert bool(context["feedback"]) == (meta["case"] == "feedback_followup")


def test_blank_ratings_are_not_results_and_existing_runs_are_preserved(tmp_path: Path) -> None:
    run = tmp_path / "pilot"
    write_packets(run, repeats=1)
    assert summarize(run) == {"status": "not_run", "groups": {}}
    original = (run / "packets.jsonl").read_text()
    assert len([json.loads(line) for line in original.splitlines()]) == 6
    with pytest.raises(ValueError, match="preserved"):
        write_packets(run, repeats=1)
    assert (run / "packets.jsonl").read_text() == original
