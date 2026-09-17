# Buxter — product canon

Human-maintained authority for documentation. Preserve these boundaries; cite code for implementation claims.
If code and intent differ, document the gap instead of inventing implementation.

## Product thesis
We do not build a humanoid body. We put an evidence-backed inspection brain (SOP + visual agents + CAD bridge) onto a purchased mobile/manipulator platform for EMS / SMT incoming QC.

## Container contract
Repository: aleksandrlyubarev-blip/Buxter
System role: photo and text to parametric CAD/rework geometry.
Actor: QC/rework engineer reviewing a geometry proposal.
Input: authorized public/synthetic part photo and text dimensions/description.
Output: parametric CAD script, STL/STEP artifacts and validation results.
Implemented: src/buxter/vision.py creates CAD scripts; src/buxter/backends.py routes CAD execution.
FreeCAD is the default backend; Autodesk Fusion is optional and External.
Fusion dry-run emits a script; this does not prove successful GUI execution or valid exported geometry.
Implemented: src/buxter/validator.py and buxter validate provide mesh/printability checks.
Validation covers watertightness, volume, bounding box and sampled minimum wall thickness.
Fail-closed rule for the proposed rework flow: failed or absent validation must block release and require engineer review.
The validate command exists; do not claim every draw invocation automatically runs all printability gates.
CAD validity is not approval of a rework process, robot trajectory or part safety.
Browser/BIM features may exist in code but are not separate containers in this inspection system map.
Not demonstrated: automated defect-to-rework handoff from Neuron Vision or production connection to Romeo.

## System flow
Camera (External) -> FlexVision Checker capture/frame QA -> Romeo task routing -> Neuron Vision observations -> Inspection Copilot SOP/evidence policy -> human review/disposition -> PASS | REWORK | HOLD | HUMAN REVIEW; Buxter optionally proposes validated CAD/rework geometry.
Romeo owns orchestration and HITL; Neuron Vision owns five visual roles; Copilot owns the deterministic SOP gate.
Buxter defaults to FreeCAD, with optional Fusion and explicit validate/printability checks.
This flow is the target integration; the five repositories do not yet prove one connected deployment.
Target: verdict plus SHA-256 evidence pack including provenance and human disposition.

## External boundary
Purchased mobile base + manipulator + camera: External hardware, not our IP.
Flex line, Technion lab and Israel Physical AI testbed: External target environments, not asserted deployments.
Robot platform drivers and the unified hardware integration are not implemented by this documentation scaffold.

## Source snapshot
Initial audit: b815900e9593db6b900dd363f4bc215d01fd2e55 (2026-09-17).
Regeneration must cite the checkout being analyzed and distinguish new code from this initial audit.
Only public source code and synthetic examples may enter documentation generation.
