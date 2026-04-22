# Project Rules

## Goal
Build a research agent that transforms user queries into structured, evidence-based judgments and generates a research report.

---

## Mandatory Pipeline
define -> decompose -> retrieve -> extract -> reason -> report

---

## Core Principles

- Do not generate answers directly from the user query.
- All outputs must be derived from evidence.
- The system must model uncertainty, not hide it.
- Missing information is part of the judgment.

---

## Evidence Rules

- Do not skip the evidence layer.
- All evidence must be grounded in source content.
- Each evidence must include a source reference.
- Extract both supporting and counter evidence.
- Avoid one-sided or biased extraction.

---

## Reasoning Rules

- Do not produce conclusions without evidence support.
- All conclusions must reference evidence IDs.
- Explicitly include:
  - risks
  - unknowns
  - evidence gaps
- If evidence is insufficient, state that clearly.
- Do not overstate confidence.

---

## Evidence Gap Rules

- Identify missing but expected evidence.
- Treat missing critical data as a risk signal.
- Highlight high-priority gaps explicitly.

---

## Output Rules

- Final output must include:
  - conclusion
  - evidence references
  - risks
  - unknowns
  - evidence gaps
  - confidence
- The report must be generated from structured judgment, not directly from query.

---

## Engineering Rules

- Use FastAPI + Pydantic.
- Keep outputs structured and JSON-friendly.
- Add tests for each step.
- Prefer small, modular files.
- Keep business logic out of API routes.
- Each pipeline step must have clear input/output contracts.