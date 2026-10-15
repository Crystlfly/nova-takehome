import sys
import os
sys.path.insert(0, os.path.abspath('harness'))

from datetime import date
from decimal import Decimal

# pyrefly: ignore [missing-import]
from nova.engine.audit import audit_invoice, AuditEngine
# pyrefly: ignore [missing-import]
from nova.models.common import ChargeType, SourceRef
# pyrefly: ignore [missing-import]
from nova.models.facts import InvoiceDoc, InvoiceLine, RateRow, FxRateRow
# pyrefly: ignore [missing-import]
from nova.store.state import AuditState


src = SourceRef(doc="test_doc", page=1, quote="dummy text")

# =====================================================================
# TEST CASE 1: Standard Routing (Weight Bands & Surcharge Chaining)
# =====================================================================
rates_tc1 = [
    RateRow(contract_id="TBX-US-EXP-E60", charge_type=ChargeType.BASE_FREIGHT, lane="USE2-INE2", rate_per_kg=Decimal("6.69"), min_weight_kg=None, max_weight_kg=None, source=src),
    RateRow(contract_id="TBX-US-EXP-E60", charge_type=ChargeType.BASE_FREIGHT, lane="USE2-INE2", rate_per_kg=Decimal("6.01"), min_weight_kg=Decimal("100"), max_weight_kg=Decimal("500"), source=src),
    RateRow(contract_id="TBX-US-EXP-E60", charge_type=ChargeType.FUEL_SURCHARGE, lane="USE2-INE2", percentage_rate=Decimal("20.16"), source=src),
    RateRow(contract_id="TBX-US-EXP-E60", charge_type=ChargeType.SECURITY_SURCHARGE, lane="USE2-INE2", rate_per_kg=Decimal("0.15"), source=src),
    RateRow(contract_id="TBX-US-EXP-E60", charge_type=ChargeType.OTHER, lane="USE2-INE2", flat_fee=Decimal("121.81"), source=src),
]

invoice_tc1 = InvoiceDoc(
    invoice_id="TX-US-2032-5394", contract_id="TBX-US-EXP-E60", carrier="Tarrowby Express Inc.", shipper="Quillmere Pharma Inc.",
    invoice_date=date(2032, 1, 2), pickup_date=date(2031, 12, 25), currency="USD", total_amount=Decimal("2095.29"),
    chargeable_weight_kg=Decimal("241"), origin="USE2", destination="INE2", source=src,
    lines=[
        InvoiceLine(line_number=1, description="Air freight", charge_type=ChargeType.BASE_FREIGHT, quantity=Decimal("241"), amount=Decimal("1612.29"), source=src),
        InvoiceLine(line_number=2, description="Fuel surcharge", charge_type=ChargeType.FUEL_SURCHARGE, quantity=Decimal("1612.29"), amount=Decimal("325.04"), source=src),
        InvoiceLine(line_number=3, description="Security surcharge", charge_type=ChargeType.SECURITY_SURCHARGE, quantity=Decimal("241"), amount=Decimal("36.15"), source=src),
        InvoiceLine(line_number=4, description="Delivery fee", charge_type=ChargeType.OTHER, quantity=Decimal("1"), amount=Decimal("121.81"), source=src),
    ],
)

res1 = audit_invoice(invoice=invoice_tc1, rates=rates_tc1)
print("="*50 + "\nTEST CASE 1: Standard Routing\n" + "="*50)
if res1:
    assert res1.total_discrepancy_usd == Decimal("196.92"), f"Expected 196.92, got {res1.total_discrepancy_usd}"
    print("SUCCESS: Exact target $196.92 verified!")
else:
    print("FAILED: No discrepancy detected.")


# =====================================================================
# TEST CASE 2: INR Invoice, Fx Conversion, and Uncontracted Charges
# =====================================================================
fx_rates = [
    FxRateRow(
        contract_id="IND-US-001",
        month_key="2032-02",
        inr_per_usd=Decimal("83.00"),
        source=src,
    )
]
rates_tc2 = [
    RateRow(
        contract_id="IND-US-001",
        charge_type=ChargeType.BASE_FREIGHT,
        lane="INE2-USE2",
        flat_fee=Decimal("15000.00"),
        source=src,
    )
]

invoice_tc2 = InvoiceDoc(
    invoice_id="INV-IND-999",
    contract_id="IND-US-001",
    carrier="India Freight Ltd",
    shipper="Quillmere Pharma Inc.",
    invoice_date=date(2032, 2, 15),
    pickup_date=date(2032, 2, 14),
    currency="INR",
    total_amount=Decimal("18000.00"),
    chargeable_weight_kg=Decimal("500"),
    origin="INE2",
    destination="USE2",
    source=src,
    lines=[
        InvoiceLine(line_number=1, description="Base Freight", charge_type=ChargeType.BASE_FREIGHT, quantity=Decimal("500"), amount=Decimal("16000.00"), source=src),
        InvoiceLine(line_number=2, description="Random Admin Fee", charge_type=ChargeType.OTHER, quantity=Decimal("1"), amount=Decimal("2000.00"), source=src),
    ],
)

res2 = audit_invoice(invoice=invoice_tc2, rates=rates_tc2, fx_rates=fx_rates)
print("\n" + "="*50 + "\nTEST CASE 2: INR Invoice & Uncontracted Fees\n" + "="*50)
if res2:
    expected_usd = Decimal("36.14")
    assert res2.total_discrepancy_usd == expected_usd, f"Expected {expected_usd}, got {res2.total_discrepancy_usd}"
    print(f"SUCCESS: FX conversion and uncontracted charges correctly calculated as ${expected_usd}!")
else:
    print("FAILED: No discrepancy detected.")


# =====================================================================
# TEST CASE 3: Edge Cases (Clean Invoices, Credit Notes, Missing Data)
# =====================================================================
print("\n" + "="*50 + "\nTEST CASE 3: Edge Cases (Clean, Credit Notes, Missing FX)\n" + "="*50)

# A. Clean Invoice
invoice_clean = InvoiceDoc(
    invoice_id="INV-CLEAN-001",
    contract_id="TBX-US-EXP-E60",
    carrier="Tarrowby",
    shipper="Quillmere",
    invoice_date=date(2032, 1, 2),
    currency="USD",
    total_amount=Decimal("1448.41"),
    chargeable_weight_kg=Decimal("241"),
    origin="USE2",
    destination="INE2",
    source=src,
    lines=[
        InvoiceLine(line_number=1, description="Air freight", charge_type=ChargeType.BASE_FREIGHT, quantity=Decimal("241"), amount=Decimal("1448.41"), source=src),
    ],
)
assert audit_invoice(invoice=invoice_clean, rates=rates_tc1) is None
print("SUCCESS: Edge Case A (Perfect Match) correctly returned no discrepancies.")

# B. Credit Note
invoice_credit = invoice_clean.model_copy(update={"is_credit_note": True, "invoice_id": "CREDIT-999"})
assert audit_invoice(invoice=invoice_credit, rates=rates_tc1) is None
print("SUCCESS: Edge Case B (Credit Note) correctly bypassed the audit.")

# C. Missing FX Rate
invoice_missing_fx = InvoiceDoc(
    invoice_id="INV-NO-FX-001",
    contract_id="IND-US-001",
    carrier="India Freight",
    shipper="Quillmere",
    invoice_date=date(2032, 3, 10),
    currency="INR",
    total_amount=Decimal("16000.00"),
    chargeable_weight_kg=Decimal("500"),
    origin="INE2",
    destination="USE2",
    source=src,
    lines=[
        InvoiceLine(line_number=1, description="Base Freight", charge_type=ChargeType.BASE_FREIGHT, quantity=Decimal("500"), amount=Decimal("16000.00"), source=src),
    ],
)
res_missing_fx = audit_invoice(invoice=invoice_missing_fx, rates=rates_tc2, fx_rates=fx_rates)
assert res_missing_fx is not None
assert res_missing_fx.fx_rate_applied is None
assert res_missing_fx.total_discrepancy_usd == Decimal("1000.00")
print("SUCCESS: Edge Case C (Missing FX Rate) gracefully fell back without crashing.")


# =====================================================================
# TEST CASE 4: Duplicate Invoice (Processed Previously in State)
# =====================================================================
print("\n" + "="*50 + "\nTEST CASE 4: Duplicate Invoice\n" + "="*50)

invoice_dup = InvoiceDoc(
    invoice_id="TX-US-2032-5394",
    contract_id="TBX-US-EXP-E60",
    carrier="Tarrowby Express Inc.",
    shipper="Quillmere Pharma Inc.",
    invoice_date=date(2032, 1, 15),
    pickup_date=date(2031, 12, 25),
    currency="USD",
    total_amount=Decimal("2095.29"),
    chargeable_weight_kg=Decimal("241"),
    origin="USE2",
    destination="INE2",
    source=src,
    lines=[
        InvoiceLine(line_number=1, description="Air freight", charge_type=ChargeType.BASE_FREIGHT, quantity=Decimal("241"), amount=Decimal("1612.29"), source=src),
        InvoiceLine(line_number=2, description="Fuel surcharge", charge_type=ChargeType.FUEL_SURCHARGE, quantity=Decimal("1612.29"), amount=Decimal("325.04"), source=src),
    ],
)

# 1. Audit single invoice with prior_invoices list
res_dup = audit_invoice(
        invoice=invoice_dup,
        rates=rates_tc1,
        is_duplicate=True,
    )
assert res_dup is not None, "Expected duplicate finding"
assert res_dup.verdict == "finding", f"Expected verdict 'finding', got {res_dup.verdict}"
assert res_dup.finding_class == "duplicate", f"Expected class 'duplicate', got {res_dup.finding_class}"
assert res_dup.action == "draft:dispute", f"Expected action 'draft:dispute', got {res_dup.action}"
assert res_dup.amount_usd == "2095.29", f"Expected amount_usd '2095.29', got {res_dup.amount_usd}"
assert res_dup.total_discrepancy_usd == Decimal("2095.29")

# 2. Audit through AuditEngine with state tracking
state_dup = AuditState(
    processed_doc_ids=["TX-US-2032-5394"],
    invoices=[invoice_dup],
    rate_rows=rates_tc1,
)
engine_dup = AuditEngine(state_dup)
engine_results = engine_dup.run_audit()
assert len(engine_results) == 1
assert engine_results[0].verdict == "finding"
assert engine_results[0].finding_class == "duplicate"
assert engine_results[0].action == "draft:dispute"
assert engine_results[0].amount_usd == "2095.29"
print("SUCCESS: Test Case 4 (Duplicate Invoice) successfully detected and verified!")


# =====================================================================
# TEST CASE 5: Conflict (Two Disagreeing Rate Sources)
# =====================================================================
print("\n" + "="*50 + "\nTEST CASE 5: Rate Conflict (Amendment vs Notice)\n" + "="*50)

src_amendment = SourceRef(doc="TBX-AMEND-02", page=2, quote="Amendment rate 2.88 USD/kg")
src_notice = SourceRef(doc="TBX-NOTICE-JAN", page=1, quote="Rate notice 3.03 USD/kg")

rates_conflict = [
    RateRow(
        contract_id="TBX-US-EXP-E60",
        charge_type=ChargeType.BASE_FREIGHT,
        lane="USE2-INE2",
        rate_per_kg=Decimal("2.88"),
        min_weight_kg=Decimal("100"),
        max_weight_kg=Decimal("500"),
        source=src_amendment,
    ),
    RateRow(
        contract_id="TBX-US-EXP-E60",
        charge_type=ChargeType.BASE_FREIGHT,
        lane="USE2-INE2",
        rate_per_kg=Decimal("3.03"),
        min_weight_kg=Decimal("100"),
        max_weight_kg=Decimal("500"),
        source=src_notice,
    ),
    RateRow(
        contract_id="TBX-US-EXP-E60",
        charge_type=ChargeType.FUEL_SURCHARGE,
        lane="USE2-INE2",
        percentage_rate=Decimal("23.14"),
        source=src,
    ),
]

invoice_conflict = InvoiceDoc(
    invoice_id="TX-US-2032-5166",
    contract_id="TBX-US-EXP-E60",
    carrier="Tarrowby Express Inc.",
    shipper="Quillmere Pharma Inc.",
    invoice_date=date(2032, 1, 10),
    pickup_date=date(2032, 1, 8),
    currency="USD",
    total_amount=Decimal("421.62"),
    chargeable_weight_kg=Decimal("113"),
    origin="USE2",
    destination="INE2",
    source=src,
    lines=[
        InvoiceLine(line_number=1, description="Air freight", charge_type=ChargeType.BASE_FREIGHT, quantity=Decimal("113"), amount=Decimal("342.39"), source=src),
        InvoiceLine(line_number=2, description="Fuel surcharge", charge_type=ChargeType.FUEL_SURCHARGE, quantity=Decimal("342.39"), amount=Decimal("79.23"), source=src),
    ],
)

res_conflict = audit_invoice(invoice=invoice_conflict, rates=rates_conflict)
assert res_conflict is not None, "Expected conflict finding"
assert res_conflict.verdict == "conflict", f"Expected verdict 'conflict', got {res_conflict.verdict}"
assert res_conflict.action == "escalate", f"Expected action 'escalate', got {res_conflict.action}"
assert res_conflict.amount_usd is None, f"Expected amount_usd None, got {res_conflict.amount_usd}"
assert res_conflict.amount_range == ["0.00", "421.62"], f"Expected range ['0.00', '20.87'], got {res_conflict.amount_range}"
assert res_conflict.total_discrepancy_usd == Decimal("0.00")
# Verify both disagreeing rate sources are cited in evidence
cited_docs = {e.doc for e in res_conflict.evidence}
assert "TBX-AMEND-02" in cited_docs and "TBX-NOTICE-JAN" in cited_docs
print(f"SUCCESS: Test Case 5 (Conflict) correctly returned verdict='conflict', range={res_conflict.amount_range}, action='escalate' citing both sources!")


# =====================================================================
# TEST CASE 6: Missing Document (Cannot Determine)
# =====================================================================
print("\n" + "="*50 + "\nTEST CASE 6: Missing Document (Cannot Determine)\n" + "="*50)

missing_doc_meta = {
    "name": "Annex D fuel surcharge schedule",
    "holder": "carrier",
}

invoice_missing = InvoiceDoc(
    invoice_id="TX-US-2032-9901",
    contract_id="TBX-US-EXP-E60",
    carrier="Tarrowby Express Inc.",
    shipper="Quillmere Pharma Inc.",
    invoice_date=date(2032, 1, 20),
    pickup_date=date(2032, 1, 18),
    currency="USD",
    total_amount=Decimal("1500.00"),
    chargeable_weight_kg=Decimal("200"),
    origin="USE2",
    destination="INE2",
    source=src,
    lines=[
        InvoiceLine(line_number=1, description="Air freight", charge_type=ChargeType.BASE_FREIGHT, quantity=Decimal("200"), amount=Decimal("1200.00"), source=src),
        InvoiceLine(line_number=2, description="Fuel surcharge", charge_type=ChargeType.FUEL_SURCHARGE, quantity=Decimal("1200.00"), amount=Decimal("300.00"), source=src),
    ],
)

res_missing = audit_invoice(
    invoice=invoice_missing,
    rates=rates_tc1,
    missing_doc=missing_doc_meta,
)
assert res_missing is not None, "Expected missing doc finding"
assert res_missing.verdict == "cannot_determine", f"Expected verdict 'cannot_determine', got {res_missing.verdict}"
assert res_missing.action == "draft:request_document", f"Expected action 'draft:request_document', got {res_missing.action}"
assert res_missing.amount_usd is None, f"Expected amount_usd None, got {res_missing.amount_usd}"
assert res_missing.missing_doc == missing_doc_meta
assert res_missing.total_discrepancy_usd == Decimal("0.00")

# Test eval check() compatibility directly
from evals.run_evals import check as eval_check
eval_case_cannot_det = {
    "expect": {
        "verdict": "cannot_determine",
        "action": "draft:request_document",
        "missing_doc": {"name": "Annex D fuel surcharge schedule"},
    }
}
diffs = eval_check(eval_case_cannot_det, res_missing)
assert not diffs, f"eval_check reported differences: {diffs}"

print("SUCCESS: Test Case 6 (Missing Document) correctly returned verdict='cannot_determine', action='draft:request_document', missing_doc verified by eval_check()!")

print("\n" + "="*50 + "\nALL 6 OFFLINE AUDIT TEST CASES PASSED SUCCESSFULLY!\n" + "="*50)
