import sys
sys.path.insert(0, "harness")

from datetime import date
from decimal import Decimal
# pyrefly: ignore [missing-import]
from nova.store.state import AuditState
# pyrefly: ignore [missing-import]
from nova.models.facts import InvoiceDoc
# pyrefly: ignore [missing-import]
from nova.models.common import SourceRef
# pyrefly: ignore [missing-import]
from nova.engine.audit import AuditEngine

# 1. Create a fake historical state where TX-123 was ALREADY processed
state = AuditState(
    invoices=[], 
    rate_rows=[], 
    fx_rates=[], 
    processed_doc_ids=["TX-123"] # This ID is already in the system history
)

# 2. Receive TX-123 AGAIN in the current batch
source = SourceRef(doc="test.pdf", page=1, quote="test")
inv = InvoiceDoc(
    invoice_id="TX-123", 
    carrier="TestCarrier",
    invoice_date=date(2033, 1, 1), 
    currency="USD", 
    total_amount=Decimal("100.00"), 
    lines=[],
    source=source
)
state.invoices.append(inv)

# 3. Run your engine
engine = AuditEngine(state)
results = engine.run_audit()

# 4. Print the exact output to see what the evaluator sees
print(f"--- DIAGNOSTIC RESULTS ---")
print(f"Discrepancies found: {len(results)}")
if len(results) > 0:
    print(f"Verdict: {results[0].verdict}")
    print(f"Finding Class mapped property: {getattr(results[0], 'finding_class', 'MISSING')}")
    print(f"Dict dump default: {'class' in results[0].model_dump()}")
    print(f"Dict dump by_alias: {'class' in results[0].model_dump(by_alias=True)}")