#!/usr/bin/env python3
"""Convert Neal's CNC FreeAgent export + Kanban CSV to a Django fixture JSON.

The Excel export and the Kanban CSV are discovered automatically: the script
uses the single .xlsx and single .csv file in the datasets/ directory beside
it, and errors out if there is more than one of either.
"""
import argparse
import sys
from pathlib import Path

# Allow `python nealsdata/convert_neals_data.py` to find the `nealsdata`
# package: put the repo root (the script's grandparent) on sys.path.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def build_parser():
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument('--output', default=None,
                   help='Output fixture path (default: datasets/converted.json)')
    p.add_argument('--limit', type=int, default=100,
                   help='Approx. number of Jobs to build from recent cards '
                        '(also caps --all-vendors)')
    p.add_argument('--all-vendors', action='store_true',
                   help='Also import the newest --limit vendor orgs from the '
                        'Bills sheet even when none of their Bills yields a '
                        'PO (default: only vendors that get a PO)')
    p.add_argument('--seed-users', type=int, default=None,
                   help='Keep only the first N users from nealseed.json '
                        '(file order; default: all)')
    p.add_argument('--verbose', action='store_true')
    return p


def main():
    p = build_parser()
    args = p.parse_args()

    datasets_dir = Path(__file__).resolve().parent / 'datasets'

    from nealsdata.converter.loaders import discover_datasets
    try:
        excel, csv_path = discover_datasets(datasets_dir)
    except ValueError as exc:
        p.error(str(exc))

    output = args.output or str(datasets_dir / 'converted.json')

    from nealsdata.converter.orchestrator import NealsDataConverter
    NealsDataConverter(
        excel_path=excel, csv_path=csv_path, output_path=output,
        limit=args.limit, verbose=args.verbose, all_vendors=args.all_vendors,
        seed_user_limit=args.seed_users,
    ).convert()


if __name__ == '__main__':
    main()
