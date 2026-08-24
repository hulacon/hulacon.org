"""In-place update of questions by DataExportTag, using the spec in build_form.

Usage:
  python sync_questions.py SV_xxx Q_tag1 Q_tag2 ...

Finds each question by tag in the live survey, looks up its current spec in
build_form.BLOCKS, and PUTs the updated payload. Preserves the survey ID and
any responses already collected. Only updates existing questions — won't add
or remove."""

from __future__ import annotations

import sys
from qualtrics_client import QualtricsClient
from build_form import BLOCKS, build_payload


def spec_by_tag(tag: str) -> dict | None:
    for _, qs in BLOCKS:
        for q in qs:
            if q["tag"] == tag:
                return q
    return None


def qid_by_tag(c: QualtricsClient, survey_id: str) -> dict[str, str]:
    """Map DataExportTag -> QID for a live survey."""
    meta = c.get_survey_meta(survey_id)
    out = {}
    for qid, q in (meta.get("questions") or {}).items():
        tag = q.get("questionName")
        if tag:
            out[tag] = qid
    return out


def main() -> None:
    if len(sys.argv) < 3:
        print("usage: python sync_questions.py SV_xxx Q_tag1 [Q_tag2 ...]")
        sys.exit(1)
    survey_id, *tags = sys.argv[1:]

    c = QualtricsClient()
    tag_to_qid = qid_by_tag(c, survey_id)

    for tag in tags:
        spec = spec_by_tag(tag)
        if spec is None:
            print(f"  {tag}: not in build_form.BLOCKS — skipped")
            continue
        qid = tag_to_qid.get(tag)
        if not qid:
            print(f"  {tag}: not found in survey {survey_id} — skipped")
            continue
        payload = build_payload(spec)
        c.update_question(survey_id, qid, payload)
        print(f"  {tag} ({qid}): updated")


if __name__ == "__main__":
    main()
