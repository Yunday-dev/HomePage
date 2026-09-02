#!/usr/bin/env python3
"""Build ../index.json from worklog metadata in ../reports/**/*.html."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path


WORKLOG_META = {
    "worklog-date": "date",
    "worklog-title": "title",
    "worklog-project": "project",
    "worklog-tags": "tags",
    "worklog-summary": "summary",
    "worklog-visibility": "visibility",
}


class WorkLogParser(HTMLParser):
    """Extract worklog metadata, title, and a small plain-text fallback."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.metadata: dict[str, str] = {}
        self.title_parts: list[str] = []
        self.text_parts: list[str] = []
        self._in_title = False
        self._ignored_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {key.lower(): (value or "") for key, value in attrs}
        tag = tag.lower()
        if tag == "meta":
            name = attributes.get("name", "").lower()
            if name in WORKLOG_META:
                self.metadata[WORKLOG_META[name]] = attributes.get("content", "").strip()
        elif tag == "title":
            self._in_title = True
        elif tag in {"script", "style", "svg", "noscript"}:
            self._ignored_depth += 1

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "title":
            self._in_title = False
        elif tag in {"script", "style", "svg", "noscript"} and self._ignored_depth:
            self._ignored_depth -= 1

    def handle_data(self, data: str) -> None:
        text = " ".join(data.split())
        if not text:
            return
        if self._in_title:
            self.title_parts.append(text)
        elif not self._ignored_depth:
            self.text_parts.append(text)


def read_report(path: Path, root: Path) -> tuple[dict[str, object], list[str]]:
    parser = WorkLogParser()
    parser.feed(path.read_text(encoding="utf-8-sig"))
    metadata = parser.metadata
    warnings: list[str] = []

    filename_date = re.match(r"(\d{4}-\d{2}-\d{2})", path.name)
    date = metadata.get("date") or (filename_date.group(1) if filename_date else "")
    if not date:
        warnings.append("worklog-date가 없고 파일명에서도 날짜를 찾지 못했습니다")

    title = metadata.get("title") or " ".join(parser.title_parts) or path.stem
    if "title" not in metadata:
        warnings.append("worklog-title이 없어 <title> 또는 파일명을 사용했습니다")

    project = metadata.get("project") or "Development"
    if "project" not in metadata:
        warnings.append("worklog-project가 없어 Development를 사용했습니다")

    summary = metadata.get("summary", "")
    if not summary:
        plain_text = " ".join(parser.text_parts)
        summary = plain_text[:177].rstrip() + ("…" if len(plain_text) > 177 else "")
        warnings.append("worklog-summary가 없어 본문에서 요약을 만들었습니다")

    tags = [tag.strip() for tag in metadata.get("tags", "").split(",") if tag.strip()]
    relative_file = path.relative_to(root).as_posix()

    report: dict[str, object] = {
        "date": date,
        "title": title,
        "project": project,
        "tags": tags,
        "summary": summary,
        "file": relative_file,
    }
    if metadata.get("visibility"):
        report["visibility"] = metadata["visibility"]
    return report, warnings


def build_index(root: Path, output: Path) -> int:
    reports_dir = root / "reports"
    reports: list[dict[str, object]] = []
    warning_count = 0

    for path in sorted(reports_dir.rglob("*.html")) if reports_dir.exists() else []:
        try:
            report, warnings = read_report(path, root)
            reports.append(report)
            for warning in warnings:
                warning_count += 1
                print(f"warning: {path.relative_to(root)}: {warning}", file=sys.stderr)
        except (OSError, UnicodeError) as error:
            print(f"error: {path.relative_to(root)}: {error}", file=sys.stderr)
            return 1

    reports.sort(key=lambda item: (str(item.get("date", "")), str(item.get("title", ""))), reverse=True)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "reports": reports,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Indexed {len(reports)} report(s) into {output.relative_to(root)} ({warning_count} warning(s)).")
    return 0


def main() -> int:
    default_root = Path(__file__).resolve().parents[1]
    argument_parser = argparse.ArgumentParser(description=__doc__)
    argument_parser.add_argument("--root", type=Path, default=default_root, help="저장소 루트 디렉터리")
    argument_parser.add_argument("--output", type=Path, help="생성할 index.json 경로")
    args = argument_parser.parse_args()

    root = args.root.resolve()
    output = args.output.resolve() if args.output else root / "index.json"
    return build_index(root, output)


if __name__ == "__main__":
    raise SystemExit(main())
