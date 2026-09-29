"""Public business report checks, separate from numeric gold and Runtime authority.

The v2 public contract additionally requires the short source context sentence
in the report body, including its qualifiers. This is an extractive coverage
check, not a general natural-language entailment or causality judge.
"""
from __future__ import annotations

import re

REPORT_CONTRACT_VERSION = "stage1-report-v2-extractive-context"

REPORT_INSTRUCTIONS = (
    "Write exactly one complete statement per output entity, on its own line/claim. "
    "The report body (claim_text or summary) MUST contain all four required parts: "
    "(1) the exact unit_id/site_id; (2) risk=true or risk=false, copied from the current risk field: prefer current_under_budget/current_below_20_pct/current_exceeds_slo when present, otherwise below_20_pct/exceeds_slo/under_budget; "
    "(3) risk_change=<the exact row value>; (4) the complete current background sentence. "
    "Use literal '=' separators in risk=<boolean> and risk_change=<value>, NOT ':' or natural-language substitutes. "
    "claim_id is an identifier only: entity/risk/change written there do NOT count as report content. "
    "In a text report include its exact note_locator/event_locator; "
    "in a typed ClaimSet use the supporting evidence ID for that entity's section. "
    "Include the complete current note/event sentence for that entity verbatim in the report body "
    "(claim_text or summary), omitting only its entity/period prefix. Preserve all qualifiers, "
    "including uncertainty; putting context only in uncertainty_note is insufficient. "
    "Treat the quoted context as a published fact, not proof of the cause of a computed risk. "
    "Cite the entity's actual note/event section, not the document title or generic scope."
)


def report_feedback(errors):
    """Explain public syntax/coverage failures, never supply business answers."""
    rules = {
        "report_entity_statement_count": ("claims/summary", "Return exactly one statement per supplied verified row."),
        "report_entity_coverage": ("claim_text", "Include the exact entity ID from the verified row in ONE body, not only claim_id."),
        "report_risk": ("claim_text", "Write exactly one risk=<boolean> label using the literal '=' character, not 'risk:'. Copy the verified row's current risk boolean: prefer current_under_budget/current_below_20_pct/current_exceeds_slo, otherwise below_20_pct/exceeds_slo/under_budget."),
        "report_change": ("claim_text", "Write exactly one risk_change=<value> label using the literal '=' character, not 'risk_change:'. Copy the exact risk_change string from the verified row."),
        "report_source_binding": ("source_locator", "Use the current entity's published note/event section, not a different entity or period."),
        "report_current_context": ("claim_text", "Include the complete current source sentence verbatim, with all qualifiers; uncertainty_note alone does not count."),
        "report_current_locator": ("summary", "Include the complete verified note_locator/event_locator filename#section in this entity's body."),
        "report_entity_evidence": ("supporting_evidence_item_ids", "Cite the supplied evidence for this entity's current source section, not the title or another entity."),
        "report_numeric_value": ("numeric_fields", "Copy each numeric field from the SAME entity's verified row, retaining its sign and decimal position. Do not recalculate percentages, rescale, or round verified values."),
    }
    result = []
    for error in errors:
        code, _, detail = error.partition(":")
        entity, _, numeric_field = detail.partition(":")
        if code in rules:
            field, requirement = rules[code]
            if code == "report_numeric_value":
                field = "numeric_fields." + numeric_field
            result.append({"error": error, "entity": entity, "field": field, "requirement": requirement})
    return result


def _normalize(text):
    return " ".join(text.split())


def report_sources(notes, *, source_name, period, entities):
    """Bind the published Stage1 prose only; never use numeric reference answers."""
    sources = {}
    for entity in entities:
        sections = re.findall(r"^## " + re.escape(entity) + r"\n(.*?)(?=^## |\Z)", notes, re.M | re.S)
        if len(sections) != 1:
            raise ValueError("report_source_section_count:" + entity)
        source_text = _normalize(sections[0])
        prefix = f"{entity} {period}: "
        if not source_text.startswith(prefix) or not source_text[len(prefix):]:
            raise ValueError("report_source_current_context_missing:" + entity)
        sources[entity] = {"locator": f"{source_name}#{entity}", "source_text": source_text,
                           "context": source_text[len(prefix):]}
    return sources




def _current_risk_value(row):
    """Return the risk flag for the current output period.

    Cross-period contracts qualify the flag as ``current_*`` so the prior
    period can be reported beside it. The report scorer must use that public
    output field before falling back to the single-period names.
    """
    for key in (
        "current_under_budget",
        "current_below_20_pct",
        "current_exceeds_slo",
        "below_20_pct",
        "exceeds_slo",
        "under_budget",
    ):
        if key in row:
            return row[key]
    return None

def report_errors(rows, statements, *, sources, evidence_items=None):
    errors = []
    if not isinstance(statements, list):
        statements = []
    if len(statements) != len(rows):
        errors.append('report_entity_statement_count')
    for row in rows:
        entity = str(row.get('unit_id', row.get('site_id', '')))
        source = sources[entity]
        matching = [s for s in statements if re.search(
            r'(?<![\w-])' + re.escape(entity) + r'(?![\w-])', str(s.get('claim_text', '')))]
        if len(matching) != 1:
            errors.append('report_entity_coverage:' + entity)
            # Diagnostic association only. Never give entity coverage credit to
            # claim_id, citations or context outside claim_text. A uniquely cited
            # source lets one repair see the other missing body fields as well.
            evidence_ids = {e['id'] for e in evidence_items or ()
                            if source['source_text'] in _normalize(e['text'])}
            matching = [s for s in statements
                        if evidence_ids.intersection(s.get('supporting_evidence_item_ids', []))
                        or source['locator'] in str(s.get('claim_text', ''))]
            if len(matching) != 1:
                continue
        statement = matching[0]
        if evidence_items is not None:
            # Check typed numeric copying in the same bounded repair as the
            # report body. Waiting for the combined ClaimSet loses the rejected
            # candidate and needlessly regenerates the other, correct batches.
            # These are verified execution rows, not independent scorer gold.
            for field, value in statement.get('numeric_fields', {}).items():
                expected_value = row.get(field)
                if (type(value) not in (int, float) or type(expected_value) not in (int, float)
                        or value != expected_value):
                    errors.append(f'report_numeric_value:{entity}:{field}')
        text = str(statement.get('claim_text', ''))
        risk = _current_risk_value(row)
        expected = 'true' if risk else 'false'
        flags = re.findall(r'\brisk\s*=\s*(true|false)\b', text, re.I)
        if [s.lower() for s in flags] != [expected]:
            errors.append('report_risk:' + entity)
        changes = re.findall(r'\brisk_change\s*=\s*(\w+)', text)
        if changes != [row['risk_change']]:
            errors.append('report_change:' + entity)
        locator = str(row.get('note_locator', row.get('event_locator', '')))
        if locator != source['locator']:
            errors.append('report_source_binding:' + entity)
        if source['context'] not in _normalize(text):
            errors.append('report_current_context:' + entity)
        if evidence_items is None and locator not in text:
            errors.append('report_current_locator:' + entity)
        if evidence_items is not None:
            cited = [e for e in evidence_items if e['id'] in statement.get('supporting_evidence_item_ids', [])]
            valid = [e for e in cited if source['source_text'] in _normalize(e['text'])
                     and e['locator'] in statement.get('citation_locators', [])]
            if not valid:
                errors.append('report_entity_evidence:' + entity)
    return errors


def text_statements(text):
    if not isinstance(text, str):
        return []
    return [{'claim_text': line.strip()} for line in text.splitlines() if line.strip()]
