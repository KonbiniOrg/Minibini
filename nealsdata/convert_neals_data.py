#!/usr/bin/env python3
"""Convert Neal's CNC FreeAgent export + Kanban CSV to a Django fixture JSON."""
import argparse


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('excel', help='Path to the FreeAgent .xlsx export')
    p.add_argument('--csv', default='nealsdata/datasets/neals kanban.csv',
                   help='Path to the Kanban board CSV export')
    p.add_argument('--output', default='nealsdata/datasets/converted.json')
    p.add_argument('--limit', type=int, default=100,
                   help='Approx. number of Jobs to build from recent cards')
    p.add_argument('--verbose', action='store_true')
    args = p.parse_args()

    from nealsdata.converter.orchestrator import NealsDataConverter
    NealsDataConverter(
        excel_path=args.excel, csv_path=args.csv, output_path=args.output,
        limit=args.limit, verbose=args.verbose,
    ).convert()


if __name__ == '__main__':
    main()
