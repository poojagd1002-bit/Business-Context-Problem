# Supplier Acknowledgement & Schedule Impact Management

A deterministic synthetic-data project for a supplier acknowledgement workflow. It creates CSV files, JSON ground truth, and a SQLite database. All supplier and transaction data are synthetic.

## Requirements
- Python 3.10+ (no third-party packages required)
- VS Code (optional)

## Run in VS Code terminal
```bash
python generate_data.py --scale starter
```
This creates `output/` with a small dataset for quick testing.

Generate the requested full volume:
```bash
python generate_data.py --scale full --seed 20261022
```
This creates 10,000 purchase orders and 15,000 acknowledgement/change events (supplier-silence events are separately recorded as ground-truth exceptions). The script also exports each entity to CSV, ground truth to CSV/JSON, a SQLite database, a data dictionary, source manifest, and validation summary.

Reproducibility:
```bash
python generate_data.py --scale starter --seed 20261022 --out run_a
python generate_data.py --scale starter --seed 20261022 --out run_b
```
Compare the `csv_sha256` values in each `validation_summary.json`. Matching hashes demonstrate identical CSV output for the same seed and scale.

## Business rules
- Quantity approval threshold: more than 10% change.
- Date approval threshold: more than 3 days of movement.
- Price approval threshold: more than 5% change.
- Changes over the threshold require an Approval record. InventoryPlan is updated only for approved or approval-not-required changes.
- Ground truth is stored separately and must not be used as a model input feature.
- Anomaly cases include wrong PO-line reference, promised date before order date, supplier silence, and a pending change that must not update projected supply.

## Files
- `generate_data.py`: fixed-seed data generator and validation.
- `output/*.csv`: entity datasets.
- `output/ground_truth.csv` and `.json`: expected outcomes and known issue labels.
- `output/supplier_workflow.sqlite`: queryable SQLite export.
- `output/data_dictionary.json`: field and validation notes.
- `output/validation_summary.json`: row counts, errors, anomaly counts and CSV checksums.
- `output/source_manifest.json`: provenance record.

## Limitations / implementation notes
This is a synthetic challenge implementation, not a production ERP integration. Carrier/warehouse roles are represented through logistics-related impact notifications and can be expanded with Shipment and Receipt entities. The generator includes an intentional wrong-line acknowledgement anomaly, which should be quarantined by the validation layer rather than silently corrected. Always inspect `issue_type` and the separate ground-truth file when evaluating the negative scenarios.
