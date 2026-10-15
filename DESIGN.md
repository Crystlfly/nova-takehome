## Fact model
The system leverages strict Pydantic models for structured data representation, ensuring that financial amounts are maintained securely as Decimal instances to completely prevent any floating-point arithmetic drift.

## Conflicts
Whenever multiple active rate rows disagree on base freight pricing for the same lane, the engine flags a conflict verdict and generates an explicit amount range citing all competing sources.

## Confidence
Confidence scores are assigned statically based on extraction completeness and match specificity, defaulting to a high confidence threshold for direct rate-card matches and lower for ambiguous missing fields.

## People in the loop
For any ambiguous discrepancies or uncontracted fees, the system triggers drafting actions that require a human operator's explicit review and approval before proceeding with the final execution.

## Feedback
Feedback data ingested via the feedback JSON file is used to dynamically update the audit state, allowing downstream reports to natively incorporate human overrides and rule adjustments.

## New documents
The document parser dynamically routes incoming PDF and Excel files based on filename signatures and structural headers, seamlessly appending new rate sheets or invoices directly into the existing state graph.

## Cost
The architecture is heavily optimized for low-latency and low-cost execution by leveraging efficient inference limits and structured parsing constraints, minimizing token waste and completely eliminating unnecessary retry loops.

## What I'd do next
If I had more time, I would definitely implement graph-based historical trend analysis for predictive carrier warnings and expand the automated waiver validation logic for quarterly volume rebates.
