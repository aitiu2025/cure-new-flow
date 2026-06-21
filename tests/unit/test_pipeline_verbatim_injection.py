"""End-to-end-ish test that the RAW + Title prompt builders inject the
verbatim Legal Description block and APN-preservation rules.

Uses a tmp_path-only fixture so it does not depend on the live MONTOYA
case dir. See docs/audits/legal_description_ordering_audit_2026-05-18.md.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from titlepro.automation.pipeline import (
    MANDATORY_VERBATIM_RULES,
    RecorderAutomationPipeline,
    SearchRequest,
    WorkflowConfig,
)


@pytest.fixture
def montoya_like_case(tmp_path, monkeypatch):
    """Build a minimal case_dir with the files the prompt builders need."""
    from titlepro import DOWNLOAD_DIR  # noqa: PLC0415

    case_root = tmp_path / "mock_case"
    case_root.mkdir()
    monkeypatch.setattr(
        "titlepro.automation.pipeline.DOWNLOAD_DIR",
        case_root,
    )

    cfg = WorkflowConfig(
        owner_name="MONTOYA Marcelino",
        county="contra_costa",
        search_requests=[SearchRequest(name="MONTOYA MARCELINO")],
        property_address="1724 Wesley Ave, El Cerrito, CA 94530",
        apn="502-153-010-9",
        output_folder_name="ContraCosta_MONTOYA_Marcelino",
        state="CA",
    )
    pipeline = RecorderAutomationPipeline(cfg)

    # documents_found.json
    docs = [
        {
            "document_number": "2026-0022802",
            "document_type": "DEED OF TRUST",
            "recording_date": "3/9/2026",
            "grantors": "MONTOYA MARCELINO",
            "grantees": "",
        },
    ]
    pipeline.documents_found_path().write_text(json.dumps(docs), encoding="utf-8")

    # document_metadata.json (load_metadata format)
    metadata = {"2026-0022802": {"filename": "B49178046.pdf"}}
    (pipeline.case_dir / "document_metadata.json").write_text(
        json.dumps(metadata), encoding="utf-8"
    )

    # _extracted.md fixture with verbatim Exhibit A
    extracted = (
        "## Page 11 (ocr)\n"
        "EXHIBIT A\n\n"
        "THE LAND REFERRED TO IS SITUATED IN THE COUNTY OF\n"
        "CONTRA COSTA, CITY OF EL CERRITO, STATE OF CALIFORNIA,\n"
        "AND IS DESCRIBED AS FOLLOWS:\n\n"
        "LOT 10, AS SHOWN ON THE MAP OF JUSTICE SUBDIVISION, UNIT\n"
        "NO. 2, CITY OF EL CERRITO, COUNTY OF CONTRA COSTA,\n"
        "CALIFORNIA, WHICH MAP WAS FILED IN THE OFFICE OF THE\n"
        "RECORDER OF THE COUNTY OF CONTRA COSTA, STATE OF\n"
        "CALIFORNIA, ON JULY 24, 1953, IN VOLUME 51 OF MAPS, PAGE 30.\n\n"
        "EXCEPTING THEREFROM THE MINERALS AND MINERAL RIGHTS\n"
        "RESERVED IN THE DEED FROM RECONSTRUCTION FINANCE\n"
        "CORPORATION TO NOBLE F. JUSTICE, ET UX., DATED OCTOBER\n"
        "13, 1952, RECORDED NOVEMBER 26, 1952, IN BOOK 2032 OF\n"
        "OFFICIAL RECORDS OF CONTRA COSTA COUNTY, PAGE 145.\n\n"
        "THIS BEING THE SAME PROPERTY CONVEYED TO MARCELINO\n"
        "MONTOYA AND SARA MONTOYA, HUSBAND AND WIFE AS JOINT\n"
        "TENANTS, DATED 06/12/2018 AND RECORDED ON 06/19/2018 IN\n"
        "INSTRUMENT NO. 2018-0097205-00, IN THE CONTRA COSTA\n"
        "COUNTY RECORDERS OFFICE.\n\n"
        "PARCEL NO. 502-153-010-9\n"
    )
    (pipeline.case_dir / "B49178046_extracted.md").write_text(extracted, encoding="utf-8")

    # Minimal extracted summary so phase guards pass.
    extracted_summary = {
        "success": True,
        "validated_documents": 1,
        "extracted_documents": 1,
        "documents": [
            {
                "document_number": "2026-0022802",
                "filename": "B49178046.pdf",
                "extracted_markdown": "B49178046_extracted.md",
                "total_chars": len(extracted),
                "ocr_used": True,
            }
        ],
    }
    pipeline.extraction_summary_path().write_text(
        json.dumps(extracted_summary), encoding="utf-8"
    )

    # Minimal placeholder PDF so PyMuPDF fallback never trips. The
    # extractor preferred extracted_md so the PDF is not strictly needed
    # but downstream excerpt builder reads it via filename.
    return pipeline


def test_extract_legal_descriptions_captures_verbatim_apn_with_check_digit(montoya_like_case):
    result = montoya_like_case.extract_legal_descriptions()
    assert result["success"] is True
    assert result["deeds_inspected"] == 1
    assert result["with_legal_description"] == 1
    assert result["with_apn"] == 1

    sidecar = json.loads(montoya_like_case.legal_descriptions_path().read_text())
    entry = sidecar["2026-0022802"]
    # Check digit preserved
    assert entry["apn_verbatim"] == "502-153-010-9"
    assert "VOLUME 51 OF MAPS" in entry["legal_description_verbatim"]
    assert "EXCEPTING THEREFROM" in entry["legal_description_verbatim"]
    assert "THIS BEING THE SAME PROPERTY CONVEYED" in entry["legal_description_verbatim"]
    assert entry["anchor_used"] == "EXHIBIT A"
    assert entry["extraction_source"] == "extracted_md"


def test_raw_prompt_includes_verbatim_block_and_rules(montoya_like_case):
    # Pre-populate the sidecar so the prompt builder picks it up.
    montoya_like_case.extract_legal_descriptions()
    prompt = montoya_like_case._build_raw_user_prompt()

    # Verbatim section header present
    assert "## Verbatim Legal Descriptions" in prompt
    # APN check digit survived into the prompt
    assert "502-153-010-9" in prompt
    # Key substantive clauses present
    assert "EXCEPTING THEREFROM" in prompt
    assert "VOLUME 51 OF MAPS" in prompt
    assert "THIS BEING THE SAME PROPERTY CONVEYED" in prompt
    # Mandatory rules appended
    assert "MANDATORY VERBATIM RULES" in prompt
    assert "do NOT drop trailing check digits" in prompt


def test_title_prompt_includes_verbatim_block_and_rules(montoya_like_case):
    montoya_like_case.extract_legal_descriptions()
    # The title prompt builder reads raw_markdown_path -- create a stub.
    raw_md = (
        "## PHASE 1: RECORDER NAME SEARCHES\nstub\n\n"
        "## PHASE 2: DOCUMENT INVENTORY & CLASSIFICATION\nstub\n\n"
        "## PHASE 3: DOCUMENT RETRIEVAL & DATA EXTRACTION\nstub\n\n"
        "## PHASE 4: TAX & PROPERTY LOOKUP\nstub\n\n"
        "## PHASE 5: RAW EXAM REPORT\nstub\n"
    )
    montoya_like_case.raw_markdown_path().write_text(raw_md, encoding="utf-8")

    prompt = montoya_like_case._build_title_user_prompt()
    assert "## Verbatim Legal Descriptions" in prompt
    assert "502-153-010-9" in prompt
    assert "MANDATORY VERBATIM RULES" in prompt
    assert "## LEGAL DESCRIPTION (EXHIBIT A)" in prompt


def test_extract_apn_from_artifacts_returns_longest_form(montoya_like_case):
    # Build with documents_found shorter APN + sidecar longer APN, the
    # function must prefer the longest (check-digit-preserving) form.
    montoya_like_case.extract_legal_descriptions()
    # Patch documents_found.json to ALSO include the shorter form to
    # simulate the dual-source race.
    docs_path = montoya_like_case.documents_found_path()
    docs = json.loads(docs_path.read_text())
    docs[0]["apn"] = "502-153-010"  # 9-digit shorter
    docs_path.write_text(json.dumps(docs), encoding="utf-8")

    result = montoya_like_case._extract_apn_from_artifacts()
    assert result == "502-153-010-9", f"expected check-digit form, got {result!r}"
