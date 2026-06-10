<div align="center">

# CoreSync

### Multi-Agent Identity Governance for Enterprise Certification Programs

<br/>

[![Status](https://img.shields.io/badge/status-active-brightgreen?style=for-the-badge)](https://github.com)
[![Track](https://img.shields.io/badge/track-Reasoning%20Agents-6f42c1?style=for-the-badge&logo=OpenAI&logoColor=white)](https://github.com)
[![Hackathon](https://img.shields.io/badge/Agents%20League-Hackathon%202026-ff6b35?style=for-the-badge)](https://github.com)
[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![Azure OpenAI](https://img.shields.io/badge/Azure%20OpenAI-0078D4?style=for-the-badge&logo=microsoftazure&logoColor=white)](https://azure.microsoft.com)
[![Microsoft Foundry](https://img.shields.io/badge/Microsoft%20Foundry%20IQ-5C2D91?style=for-the-badge&logo=microsoft&logoColor=white)](https://microsoft.com)
[![Dataverse](https://img.shields.io/badge/Dataverse-742774?style=for-the-badge&logo=powerapps&logoColor=white)](https://powerplatform.microsoft.com)

<br/>

> **CoreSync** is an autonomous multi-agent reasoning pipeline that acts as the data ingestion,
> validation, and governance gateway for an organization's enterprise learning ecosystem.
> It eliminates identity inconsistencies between HR systems, Microsoft Learn portals, and OCR
> certificate pipelines - replacing manual reconciliation cycles with grounded, auditable,
> AI-driven decisions backed by Microsoft Foundry IQ policies.

<br/>

<img src="assets/cover.png" alt="CoreSync Cover" width="800"/>

</div>

---

## The Problem

Enterprise certification programs operate across multiple disconnected data sources: HR databases,
Microsoft Learn portals, OCR-processed physical certificates, and legacy import systems. Each source
uses different Employee ID formats, name casing conventions, and data quality standards.

The result is a fragmented identity landscape where the same employee exists as three different
records that no automated system can reconcile without human intervention.

| Pain Point | Impact |
|---|---|
| Employee ID format inconsistencies between SYS-MSLEARN and SYS-HR-DATABASE | Failed join operations, duplicate registrations |
| OCR character substitution errors in scanned certificates | Valid certifications rejected by automated validators |
| Name casing and whitespace variance across source systems | Matching failures on identical individuals |
| Corrupted records from legacy migration batches | Manual triage overhead, governance gaps |
| No grounded audit trail for identity decisions | Compliance and certification integrity risk |

---

## The Solution

CoreSync deploys a **multi-agent reasoning pipeline** where each agent has a single, well-defined
responsibility. The pipeline is grounded against a Foundry IQ Knowledge Base of corporate audit
rules, so every decision is traceable to a specific policy - not a free-form LLM inference.

- **Grounded reasoning** - every match or rejection cites the specific Audit Rule that governed it
- **Cascading normalization** - Employee IDs and names are standardized before any comparison
- **Resilient batch processing** - one corrupted record does not halt the entire pipeline
- **Escalation-aware** - records that cannot be auto-resolved are routed to DataGovernance with full context
- **Audit-ready output** - all decisions are written to Dataverse with confidence scores and reasoning traces

---

## Multi-Agent Architecture

CoreSync is composed of three cooperating agents and one Foundry IQ integration layer:

```
data/synthetic_records.json
         |
         v
[ Agent 1: Curation Agent ]       agent/normalizer.py
  - Normalizes Employee IDs
  - Strips diacritics from names
  - Generates SHA-256 hashes for deduplication
  - Isolates failed records without halting batch
         |
         v
[ Foundry IQ Connector ]          connectors/foundry.py
  - Retrieves grounded Audit Rules from Knowledge Base
  - Injects AuditContext into the reasoning prompt
  - Provides source system trust coefficients
         |
         v
[ Agent 2: Resolver Agent ]       agent/resolver.py
  - Builds Chain of Thought prompt per record pair
  - Calls Azure OpenAI with AuditContext injected
  - Parses structured JSON response into ResolutionResult
  - Cites specific Audit Rules in every decision
         |
         v
[ Dataverse / Audit Report ]
  - Matched records flagged for ingestion
  - Escalated records routed to DataGovernance queue
  - Full reasoning trace stored per resolution
```

### Agent Responsibilities

**`DataNormalizer` (agent/normalizer.py)**
Stateless, side-effect-free curation agent. All methods are static, making it safe for concurrent
execution within Foundry IQ's multi-threaded runtime. Handles Employee ID format normalization,
NFKD unicode decomposition for name fields, SHA-256 hashing for PII-safe deduplication, and
batch processing with per-record error isolation.

**`FoundryIQConnector` (connectors/foundry.py)**
Simulates retrieval of grounded audit policy documents from a Microsoft Foundry IQ indexed
Knowledge Base. Returns an `AuditContext` containing numbered `AuditRule` objects, domain policies,
and source system trust coefficients. In production, `fetch_audit_context()` replaces the in-memory
fixture with an authenticated Foundry IQ REST call backed by Dataverse.

**`DataResolver` (agent/resolver.py)**
The core reasoning agent. Injects the `AuditContext` as a system prompt, builds a Chain of Thought
user prompt from the normalized record pair, and calls Azure OpenAI with `response_format:
json_object` enforced. Returns a `ResolutionResult` with `match_status`, `confidence_score`,
and `reasoning` - or an `error_state` that never halts the pipeline.

---

## Microsoft Foundry IQ Integration

The central architectural decision in CoreSync is using Foundry IQ not just as an orchestration
layer, but as a **grounding mechanism against hallucination**.

Without grounding, an LLM asked to reconcile two records might produce a confident but fabricated
justification. CoreSync prevents this by injecting 6 numbered Audit Rules into every prompt before
reasoning begins. The model is instructed to cite specific rules in its output.

The result: every `ResolutionResult.reasoning` field contains explicit citations like
`[Grounded on: Audit Rule #2, Audit Rule #3]` - making each decision traceable to a corporate
policy rather than a statistical pattern.

Key Foundry IQ Audit Rules (sample):

| Rule | Title | Effect |
|---|---|---|
| #1 | Employee ID Format Normalization | Strips UPN prefixes before comparison |
| #2 | OCR Character Substitution Detection | Corrects 0/O, 1/I, 5/S scan errors; boosts confidence +0.15 |
| #3 | High Practice Score - Strict Identity | Enforces 0.90 threshold for scores > 75% |
| #4 | Corrupted Record Escalation Protocol | Routes unrecoverable records to DataGovernance |
| #5 | Name Whitespace and Casing Normalization | Applies NFKD + collapse before name comparison |
| #6 | Baseline Clean Record Validation | Auto-approves clean matches at confidence >= 0.97 |

---

## Tech Stack

| Layer | Technology | Role |
|---|---|---|
| Reasoning Engine | Azure OpenAI (GPT-4o) | Multi-step Chain of Thought conflict resolution |
| Agent Orchestration | Microsoft Foundry IQ | Policy grounding, agent lifecycle, memory |
| Data Layer | Microsoft Dataverse | Unified record storage, audit trail, escalation queue |
| Runtime | Python 3.11+ | Agent logic, normalization pipelines, connectors |
| Integration | Power Platform Connectors | Real-time triggers from HR and Learn source systems |

---

## Quick Start

**Prerequisites**

```bash
git clone https://github.com/your-username/coresync.git
cd coresync
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

**Dry-run simulation (no Azure credentials required)**

```bash
python agent/main.py --dry-run
```

**Expected terminal output (abbreviated):**

```
========================================================================
  CORESYNC - Multi-Agent Identity Governance
  Enterprise Certification Program | Microsoft Agents League 2026
  Mode: DRY-RUN (mock resolver)
========================================================================

========================================================================
  [CURATION AGENT]  PHASE 1 - Synthetic Data Ingestion & Curation
========================================================================
    Raw records loaded        : 10
    Successfully normalized   : 10
    Failed normalization      : 0

========================================================================
  [FOUNDRY IQ CONNECTOR]  PHASE 2 - Foundry IQ Context Retrieval & Injection
========================================================================
  ============================================================
  FOUNDRY IQ - GROUNDED AUDIT CONTEXT
  Active Rules: 6 | Total Loaded: 6
  ============================================================
  [ ACTIVE AUDIT RULES ]
    Audit Rule #1 - Employee ID Format Normalization
      All Employee IDs must be normalized to a flat alphanumeric...
  ...

========================================================================
  [REASONING AGENT]  PHASE 3 - Multi-Agent Reasoning & Rule Application  [5 pairs]
========================================================================

  Pair 01 of PAIR-A  |  AZ-204  |  [ MATCH       ]
  --------------------------------------------------------------------
    Source A                  : EMP-001 (SYS-MSLEARN)
    Source B                  : EMP-002 (SYS-HR-DATABASE)
    Confidence Score          : 0.9100

    Reasoning Trace (with Foundry IQ Citations):
      Employee IDs reduce to the same sequence after stripping UPN prefix...
      [Grounded on: Audit Rule #1, Audit Rule #3]
  ...

========================================================================
  [REPORT]  PHASE 4 - Audit Report Generation
========================================================================
    Records ingested          : 10
    Matched - auto-approved   : 3
    Matched - escalated       : 1
    Not matched               : 1
    Resolution errors         : 0
    Pipeline success rate     : 100.0%
```

**Live run with Azure OpenAI**

```bash
cp .env.example .env
# Edit .env with your credentials
python agent/main.py
```

---

## Project Structure

```
coresync/
├── agent/
│   ├── __init__.py
│   ├── main.py                  - Pipeline orchestrator (4-phase execution)
│   ├── normalizer.py            - Curation Agent: ID and name normalization
│   └── resolver.py              - Reasoning Agent: Azure OpenAI CoT resolution
├── connectors/
│   ├── __init__.py
│   └── foundry.py               - Foundry IQ Knowledge Base connector
├── data/
│   └── synthetic_records.json   - 100% fictional test dataset (10 records, 5 pairs)
├── assets/
│   └── cover.png                - Project cover image
├── docs/
│   └── setup.md                 - Detailed deployment guide
├── tests/
│   └── test_normalizer.py       - Unit tests for DataNormalizer
├── .env.example                 - Environment variable template
├── requirements.txt
└── README.md
```

---

> [!WARNING]
> **SYNTHETIC DATA DISCLAIMER**
>
> 100% of the dataset in `data/synthetic_records.json` consists entirely of fabricated,
> non-existent identifiers (e.g., EMP-001, CERT-A, REG-2024-AZ204-041).
>
> This dataset contains **NO personally identifiable information (PII)**, no real employee
> records, no real certification data, and no confidential information of any kind.
>
> All names, IDs, scores, and registration numbers were invented solely for demonstration
> and evaluation purposes within the Microsoft Agents League Hackathon 2026.

---

## Community & Updates

### What is CodeNoZhiend?

This channel is my space to document the **"unfiltered side"** of programming. You'll find everything from technical breakdowns of coding and database challenges, to the culture and lifestyle behind the dev.

If you're looking for real-world layouts, algorithmic problem solving, or just want to understand what working in tech actually feels like - this is the place.

[Check out the content at **@CodeNoZhiend**](https://www.youtube.com/@CodeNoZhiend)

<div align="center">

---

*Built for the **Agents League Hackathon 2026** - Reasoning Agents Track*
*Made with precision, caffeine, and a genuine intolerance for manual processes*

</div>