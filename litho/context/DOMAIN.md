# Domain vocabulary (human-maintained canon)

| Term | Meaning in this system |
| --- | --- |
| EMS | Electronics manufacturing services; target incoming-QC operator environment. |
| SMT | Surface-mount technology for assembling electronic components on PCBs. |
| AOI | Automated optical inspection; an external/adjacent inspection method. |
| Escape rate | Fraction of truly defective inspected items incorrectly released; report denominator and ground truth. |
| SOP | Versioned standard operating procedure with traceable rule identifiers. |
| Evidence | Image/region observation linked to an SOP rule and proposed decision. |
| needs_review | Inspection Copilot fail-closed decision when evidence/quality/provider checks fail. |
| HITL | Human-in-the-loop approval, escalation and recorded disposition. |
| PASS | Proposed system release label, allowed only with sufficient verified evidence. |
| REWORK | Proposed/Neuron Vision disposition requiring an approved rework route. |
| HOLD | Containment pending review or authorized disposition; not automatic release. |
| HUMAN REVIEW | System label for unresolved cases; Copilot uses needs_review. |
| SHA-256 evidence pack | Target bundle linking image/SOP/artifact digests, evidence, decisions and approvals. |
| Sim-to-real | Transfer from simulation to physical use; not required at this stage. |

SHA-256 detects content changes; it does not prove origin, model accuracy or factory readiness.
The 2–5% manual-inspection escape-rate figure is a proposal hypothesis, not a verified industry baseline or a measured result of these repositories.
