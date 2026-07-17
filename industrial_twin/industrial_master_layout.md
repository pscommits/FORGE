# Industrial Master Layout — Panchganga Refinery & Petrochemicals Complex (PRPC)

This document is the single source of truth for the synthetic industrial data twin. Every
generated file (PDF, XLSX, CSV, MD, TXT), every knowledge-graph node/edge, and every
vectorRAG chunk must use the identifiers, naming conventions, and relationships defined
here. No downstream generator invents a new ID scheme — everything traces back to this file.

## 1. Plant Overview

- **Name:** Panchganga Refinery & Petrochemicals Complex (PRPC)
- **Location:** Raigad District, Maharashtra, India
- **Capacity:** 6.0 MMTPA (million metric tonnes per annum), commissioned 1998, last major
  revamp 2016
- **Regulatory bodies governing the site:** PESO (Petroleum & Explosives Safety
  Organisation), MoEFCC / Maharashtra Pollution Control Board (MPCB), PNGRB (Petroleum &
  Natural Gas Regulatory Board), DISH (Directorate of Industrial Safety & Health,
  Maharashtra — Factories Act 1948), OISD (Oil Industry Safety Directorate)
- **Fiscal / operating year used across all records:** April 2024 – July 2026 (documents are
  dated within this window; "today" for the data twin is **17 July 2026**)

## 2. Process Units

| Unit Code | Unit Name | Short Name | Equipment Count |
|---|---|---|---|
| 100 | Crude Distillation Unit | CDU | 10 |
| 200 | Hydrocracker Unit | HCU | 10 |
| 300 | Utilities & Offsites | UTIL | 10 |
| 400 | Tank Farm / Storage | TF | 10 |
| 500 | Effluent Treatment Plant | ETP | 10 |

Every equipment tag begins with its 3-digit unit code. Every document that discusses an
equipment item must reference the item using its full tag, never a nickname alone.

## 3. Equipment Tagging Convention

Format: **`<UnitCode>-<TypeCode>-<Sequence>`**, e.g. `100-P-101`, `200-R-201`, `300-BLR-301`.

| Type Code | Meaning |
|---|---|
| P | Centrifugal/Reciprocating Pump |
| E | Heat Exchanger |
| C | Compressor |
| V | Pressure Vessel / Knock-out Drum |
| T | Storage Tank |
| R | Reactor |
| F | Fired Heater / Furnace |
| D | Distillation Column |
| PSV | Pressure Safety Valve |
| TUR | Steam Turbine |
| BLR | Boiler |
| MTR | Motor (driver) |
| CT | Cooling Tower |
| AGT | Agitator/Mixer (ETP) |

Sequence numbers run per-unit starting at `<UnitCode>+01` (e.g. CDU pumps start at
`100-P-101`, `100-P-102`...). The full equipment master list with specs lives in
`raw_documents/master_registers/equipment_master.xlsx` and is mirrored as KG `Equipment`
nodes.

## 4. Personnel Roles

All personnel are drawn from one roster (`raw_documents/personnel_training/personnel_roster.xlsx`),
ID format **`EMP-<4 digits>`**. Roles used across documents:

Plant Manager, Process Engineer, Maintenance Engineer, Reliability Engineer, Inspection
Engineer (RBI-certified), Shift Supervisor, Panel Operator, Field Operator, HSE/Safety
Officer, Instrumentation Engineer, Electrical Engineer, Contract Technician (via OEM/AMC
vendors).

Certifications tracked: PESO Competency Certificate, RBI (Risk-Based Inspection) Level
I/II, First Aid, Confined Space Entry, Working at Height, H2S Awareness.

## 5. Document Types, ID Schemes, and File Formats

| Document Type | ID Format | File Format | Approx. Count |
|---|---|---|---|
| Equipment Datasheet | `DS-<tag>` | PDF | 50 |
| P&ID Reference / Line List | `PID-<unit>-<seq>` | PDF | 10 |
| Maintenance Work Order | `WO-<year>-<seq>` | XLSX (register) + individual PDF for major jobs | 80 |
| Inspection Report (RBI) | `IR-<tag>-<year>-<seq>` | PDF | 40 |
| Standard Operating Procedure | `SOP-<unit>-<seq>` | Markdown | 15 |
| Safety Procedure | `SP-<seq>` | Markdown | 10 |
| Incident / Near-Miss Report | `INC-<year>-<seq>` | PDF | 15 |
| Email Archive Thread | `EML-<year>-<seq>` | TXT (.eml-style) | 20 |
| Regulatory Submission | `REG-<agency>-<year>-<seq>` | PDF | 8 |
| Shift Log | `SL-<date>-<shift>` | TXT | 15 |
| Process Parameter / Sensor Log | `PL-<tag>-<year>-<month>` | CSV | 20 |
| Personnel & Training Register | `PERS-REG` | XLSX | 1 |
| Equipment Master Register | `EQ-MASTER` | XLSX | 1 |
| Work Order Master Register | `WO-MASTER` | XLSX | 1 |

Total target: ~200 files across `raw_documents/`.

## 6. Cross-Document Interconnection Rules

1. **Equipment tags are the primary join key.** A work order, inspection report, incident
   report, sensor log, SOP reference, and datasheet for `100-P-101` must all use that exact
   tag string.
2. **Personnel IDs (`EMP-####`) recur** across work orders (assigned technician), inspection
   reports (inspector), incident reports (investigator/witnesses), shift logs (supervisor on
   duty), and the personnel register.
3. **Incidents drive follow-up work orders.** An `INC-YYYY-###` that identifies equipment
   damage generates a `WO-YYYY-###` referencing that incident ID, and may trigger a revision
   of the governing SOP.
4. **SOPs and Safety Procedures are referenced, not duplicated.** Datasheets and inspection
   reports cite the SOP/SP ID that governs the equipment's operation/isolation rather than
   restating procedure text.
5. **Regulatory submissions cite incidents and inspection reports.** E.g. a PESO submission
   after a PSV incident references the `INC-` and `IR-` IDs.
6. **Emails discuss real entities.** Threads reference real work order numbers, equipment
   tags, and personnel by name — this is what makes the email archive useful for knowledge
   extraction rather than generic corporate chatter.
7. **Dates are consistent.** All documents fall between April 2024 and July 2026, and
   causally-linked documents (incident → work order → inspection follow-up) are dated in the
   correct order.

## 7. Knowledge Graph Schema

**Node types:** `ProcessUnit`, `Equipment`, `Personnel`, `SOP`, `SafetyProcedure`,
`WorkOrder`, `InspectionReport`, `Incident`, `RegulatorySubmission`, `RegulatoryBody`,
`Document` (generic wrapper for email/shift log/datasheet), `Vendor`, `ProcessParameter`.

**Edge types:** `PART_OF` (Equipment→ProcessUnit), `PERFORMED_ON` (WorkOrder→Equipment),
`ASSIGNED_TO` (WorkOrder→Personnel), `INSPECTED_BY` (InspectionReport→Personnel),
`INSPECTS` (InspectionReport→Equipment), `GOVERNED_BY` (Equipment→SOP/SafetyProcedure),
`INVOLVED_IN` (Equipment→Incident), `INVESTIGATED_BY` (Incident→Personnel),
`TRIGGERED` (Incident→WorkOrder), `REFERENCES` (RegulatorySubmission→Incident/InspectionReport),
`SUBMITTED_TO` (RegulatorySubmission→RegulatoryBody), `SUPPLIED_BY` (Equipment→Vendor),
`MONITORS` (ProcessParameter→Equipment), `SUPERVISED_BY` (ShiftLog→Personnel),
`MENTIONS` (Document/Chunk→any entity, used for hybridRAG grounding),
`CERTIFIED_IN` (Personnel→Certification, modeled as attribute).

## 8. RAG Layer Mapping

- **Knowledge Graph** (`knowledge_graph/kg_nodes_edges.json`): structured entities and
  relationships extracted from *all* document types, keyed by the IDs above — powers
  GraphRAG.
- **Vector Chunks** (`vectorrag_chunks/chunks.jsonl`): paragraph/section-level chunks from
  every text-bearing document (PDF text layer, Markdown, TXT, and cell-flattened
  XLSX/CSV rows where relevant), each tagged with `doc_id`, `source_path`, and the entity
  IDs it mentions (for hybrid grounding) — powers VectorRAG.
- **Eval set** (`eval/test_dataset.json`): questions labeled by required retrieval strategy
  (vector / graph / hybrid) and evaluation dimension, for the GraphRAG-only vs
  VectorRAG-only vs HybridRAG ablation study.

## 9. Directory Structure

```
industrial_twin/
├── industrial_master_layout.md          (this file)
├── world_model.json                     (machine-readable source of truth)
├── raw_documents/
│   ├── equipment_datasheets/            DS-*.pdf
│   ├── pid_reference/                   PID-*.pdf
│   ├── maintenance_work_orders/         WO-*.pdf (major jobs)
│   ├── inspection_reports/              IR-*.pdf
│   ├── sops/                            SOP-*.md
│   ├── safety_procedures/               SP-*.md
│   ├── incident_reports/                INC-*.pdf
│   ├── email_archive/                   EML-*.txt
│   ├── regulatory_submissions/          REG-*.pdf
│   ├── shift_logs/                      SL-*.txt
│   ├── sensor_logs/                     PL-*.csv
│   └── master_registers/                equipment_master.xlsx, work_order_register.xlsx,
│                                         personnel_roster.xlsx
├── knowledge_graph/
│   └── kg_nodes_edges.json
├── vectorrag_chunks/
│   └── chunks.jsonl
└── eval/
    ├── test_dataset.json
    └── test_dataset_readme.md
```
