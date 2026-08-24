"""Build the Hulacon Lab undergraduate research interest form.

Declarative spec below. Re-running creates a NEW survey each time (returns a
fresh SV_ ID). Use delete_survey.py to clean up old ones.

Empirical findings baked in (from probing the survey-definition API):
  - TE questions require DataExportTag.
  - Valid TE selectors: AUTO, Calendar, ESTB, FORM, ML, PW, SL.
  - Required-response needs ForceResponse=ON AND ForceResponseType=ON.
  - Email validation: ContentType="ValidEmail" (not "Email").
  - FileUpload requires Language=[] AND a Validation.Settings block.
  - Creating a block auto-appends it to SurveyFlow in order.
  - ?blockId=... on question create routes the question into that block.
  - Each block renders as its own page = automatic page breaks between blocks.
"""

from __future__ import annotations

from qualtrics_client import QualtricsClient


TITLE = "Hulacon Lab — Undergraduate Research Interest Form"

# Each block is a (name, [questions]) pair. Questions use a small DSL:
#   te(text, tag, required=..., selector="SL", content=None)
#   mc(text, tag, choices, required=...)
#   essay(text, tag, required=...)
#   file_upload(text, tag, required=...)


def te(text, tag, required=False, selector="SL", content=None):
    return {"kind": "te", "text": text, "tag": tag, "required": required,
            "selector": selector, "content": content}


def essay(text, tag, required=False):
    return {"kind": "te", "text": text, "tag": tag, "required": required,
            "selector": "ESTB", "content": None}


def mc(text, tag, choices, required=False, text_entry=None):
    """text_entry: display string of a choice that should accept free-text
    input (e.g., "Other"). Qualtrics auto-creates a _TEXT export column for it."""
    return {"kind": "mc", "text": text, "tag": tag, "required": required,
            "choices": choices, "text_entry": text_entry}


def file_upload(text, tag, required=False):
    return {"kind": "file", "text": text, "tag": tag, "required": required}


BLOCKS = [
    ("Contact", [
        te("Full name", "Q_name", required=True),
        te("UO email", "Q_email", required=True, content="ValidEmail"),
        te("Phone (optional)", "Q_phone", required=False),
    ]),
    ("Academics", [
        te("Major(s) / minor(s)", "Q_major", required=True),
        mc("Current academic year", "Q_year", required=True,
           choices=["Freshman", "Sophomore", "Junior", "Senior", "Post-bacc / Other"]),
        mc("Are you in the Clark Honors College?", "Q_chc", required=True,
           choices=["Yes", "No"]),
        te("Cumulative GPA (optional)", "Q_gpa", required=False),
    ]),
    ("Research commitment", [
        mc("How would you like to participate?", "Q_commit_type", required=True,
           choices=["For course credit", "As a volunteer", "Either is fine"]),
        mc("How many hours per week could you commit?", "Q_hours", required=True,
           choices=["3 or fewer", "4–6", "7–9", "10+"]),
        mc("When could you start?", "Q_start", required=True,
           choices=["This term", "Next term", "Other"],
           text_entry="Other"),
    ]),
    ("Interests & CV", [
        essay("What aspects of the lab's research are you most interested in?",
              "Q_interest", required=True),
        essay("Anything else you'd like us to know? (optional)",
              "Q_extra", required=False),
        mc("How did you find out about the lab?", "Q_hear", required=True,
           choices=["Hulacon Lab website", "Class / professor",
                    "Word of mouth (friend, peer)",
                    "Department listserv / email", "Other"],
           text_entry="Other"),
        file_upload("Upload your CV", "Q_cv", required=True),
    ]),
]


# ---------- payload builders ----------

def _required_validation():
    return {"Settings": {
        "ForceResponse": "ON",
        "ForceResponseType": "ON",
        "Type": "None",
    }}


def _email_validation(required: bool):
    return {"Settings": {
        "ForceResponse": "ON" if required else "OFF",
        "ForceResponseType": "ON" if required else "OFF",
        "Type": "ContentType",
        "ContentType": "ValidEmail",
    }}


def _fileupload_validation(required: bool):
    if required:
        return {"Settings": {
            "ForceResponse": "ON",
            "ForceResponseType": "ON",
            "Type": "None",
        }}
    return {"Settings": {"ForceResponse": "OFF", "Type": "None"}}


def build_payload(spec: dict) -> dict:
    kind = spec["kind"]
    if kind == "te":
        p = {
            "QuestionType": "TE",
            "Selector": spec["selector"],
            "QuestionText": spec["text"],
            "DataExportTag": spec["tag"],
        }
        if spec.get("content"):
            # currently only ValidEmail is wired
            p["Validation"] = _email_validation(spec["required"])
        elif spec["required"]:
            p["Validation"] = _required_validation()
        return p
    if kind == "mc":
        choices = {}
        for i, d in enumerate(spec["choices"]):
            entry: dict = {"Display": d}
            if spec.get("text_entry") and d == spec["text_entry"]:
                entry["TextEntry"] = "true"
            choices[str(i + 1)] = entry
        p = {
            "QuestionType": "MC",
            "Selector": "SAVR",
            "SubSelector": "TX",
            "QuestionText": spec["text"],
            "DataExportTag": spec["tag"],
            "Choices": choices,
            "ChoiceOrder": [str(i + 1) for i in range(len(spec["choices"]))],
        }
        if spec["required"]:
            p["Validation"] = _required_validation()
        return p
    if kind == "file":
        return {
            "QuestionType": "FileUpload",
            "Selector": "FileUpload",
            "QuestionText": spec["text"],
            "DataExportTag": spec["tag"],
            "Language": [],
            "Validation": _fileupload_validation(spec["required"]),
        }
    raise ValueError(f"Unknown question kind: {kind}")


# ---------- main ----------

def main() -> None:
    c = QualtricsClient()
    sv = c.create_survey(TITLE)
    sid = sv["SurveyID"]
    default_block = sv["DefaultBlockID"]
    print(f"Created survey {sid}")

    # Map block name -> block id. First block reuses the default block (renamed).
    block_ids: dict[str, str] = {}
    for i, (name, _) in enumerate(BLOCKS):
        if i == 0:
            c.update_block(sid, default_block, {"Description": name, "Type": "Default"})
            block_ids[name] = default_block
        else:
            b = c.create_block(sid, {"Type": "Standard", "Description": name})
            block_ids[name] = b["BlockID"]
        print(f"  block: {name}  ({block_ids[name]})")

    # Create questions in their blocks
    for name, questions in BLOCKS:
        bid = block_ids[name]
        for q in questions:
            payload = build_payload(q)
            r = c.create_question(sid, payload, block_id=bid)
            print(f"    {q['tag']:15s} -> {r['QuestionID']}  ({q['kind']})")

    # Activate so the anonymous link works.
    c.activate_survey(sid)

    print()
    print(f"Survey ID: {sid}")
    print(f"Public link:        {c.anonymous_link(sid)}")
    print(f"Edit (new builder): https://oregon.yul1.qualtrics.com/survey-builder/{sid}/edit")
    print(f"Edit (legacy):      https://oregon.yul1.qualtrics.com/Q/EditSection/Blocks?ContextSurveyID={sid}")


if __name__ == "__main__":
    main()
