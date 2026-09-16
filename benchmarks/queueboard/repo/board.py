"""Queueboard starter: replace the empty-snapshot stub with event replay."""

import argparse
import json


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("events")
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--format", choices=["json", "html"], default="json")
    args = parser.parse_args()
    with open(args.events) as source:
        json.load(source)
    if args.format == "json":
        print(json.dumps({"summary": {"active_count": 0, "breached_count": 0}, "tickets": []}))
    else:
        print("<!doctype html><h1>Queueboard</h1><p>0 active · 0 breached</p>")


if __name__ == "__main__":
    main()
