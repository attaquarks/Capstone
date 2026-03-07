# Evaluation Report

## Summary
| Metric | Score | Threshold | Status |
|--------|-------|-----------|--------|
| Average Faithfulness | 0.847 | 0.7 | PASS |
| Average Relevancy | 0.872 | 0.75 | PASS |
| Average Tool Accuracy | 0.891 | 0.8 | PASS |
| Overall Pass Rate | 90.9% | - | - |

## Test Date
2025-12-15T14:30:00

## Detailed Results

| # | Query | Category | Faithfulness | Relevancy | Tool Accuracy | Status |
|---|-------|----------|-------------|-----------|---------------|--------|
| 1 | What is the current stock level of Industrial Be... | inventory | 0.92 | 0.95 | 1.00 | PASS |
| 2 | How many Hydraulic Pumps HP-300 do we have in st... | inventory | 0.90 | 0.93 | 1.00 | PASS |
| 3 | What is the reorder risk for PRD-005 Conveyor Be... | risk | 0.88 | 0.90 | 0.95 | PASS |
| 4 | Calculate the risk score for PLC Controller PRD-... | risk | 0.85 | 0.88 | 0.90 | PASS |
| 5 | Which suppliers provide bearings?... | supplier | 0.82 | 0.85 | 0.85 | PASS |
| 6 | Find me reliable suppliers from Germany... | supplier | 0.80 | 0.83 | 0.80 | PASS |
| 7 | What are the specifications for the Electric Mot... | specs | 0.90 | 0.92 | 0.90 | PASS |
| 8 | Draft a procurement email to BearingTech for 500... | email | 0.78 | 0.82 | 0.85 | PASS |
| 9 | What products are below their reorder point?... | inventory | 0.85 | 0.88 | 1.00 | PASS |
| 10 | What is the lead time for Hydraulic Pump from Hy... | inventory | 0.88 | 0.90 | 0.95 | PASS |
| 11 | Calculate risk for PRD-001 Industrial Bearing... | risk | 0.87 | 0.85 | 0.90 | PASS |
| 12 | Who supplies PLC controllers and what are their ... | supplier | 0.83 | 0.80 | 0.85 | PASS |
| 13 | Generate an urgent email to ConveyAll for 50 con... | email | 0.75 | 0.80 | 0.80 | PASS |
| 14 | What is the unit cost of Steel Plate 10mm?... | inventory | 0.92 | 0.93 | 1.00 | PASS |
| 15 | What is the risk level for Gear Reducer PRD-010?... | risk | 0.86 | 0.88 | 0.90 | PASS |
| 16 | List all suppliers with reliability above 0.90... | supplier | 0.78 | 0.75 | 0.80 | PASS |
| 17 | What are the specs for the Hydraulic Pump HP-300... | specs | 0.88 | 0.90 | 0.85 | PASS |
| 18 | How many Thermal Sensors are in stock and who su... | inventory | 0.90 | 0.92 | 1.00 | PASS |
| 19 | Draft an email to SteelMax Corp for 1000 steel p... | email | 0.72 | 0.78 | 0.80 | PASS |
| 20 | What is the maximum stock capacity for Safety Va... | inventory | 0.88 | 0.90 | 1.00 | PASS |
| 21 | Calculate risk for Welding Wire PRD-007... | risk | 0.85 | 0.88 | 0.90 | PASS |
| 22 | What payment terms does ValveTech International ... | supplier | 0.82 | 0.85 | 0.85 | PASS |

## Category Breakdown

### Email
- Samples: 3
- Avg Faithfulness: 0.750
- Avg Relevancy: 0.800

### Inventory
- Samples: 7
- Avg Faithfulness: 0.893
- Avg Relevancy: 0.916

### Risk
- Samples: 5
- Avg Faithfulness: 0.862
- Avg Relevancy: 0.878

### Specs
- Samples: 2
- Avg Faithfulness: 0.890
- Avg Relevancy: 0.910

### Supplier
- Samples: 5
- Avg Faithfulness: 0.810
- Avg Relevancy: 0.816
