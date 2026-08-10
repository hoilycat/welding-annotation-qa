"""Annotation 폴더를 검사해 사람이 읽고 자동화에 사용할 수 있는 QA 리포트를 만든다."""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
from typing import Any

from .models import ParsingError
from .riawelc_reader import parse_riawelc_json
from .taxonomy import TaxonomyConfig


def _read_validated_file_modality(path: Path) -> str:
    """parser 검증을 통과한 빈 annotation JSON에서 modality를 다시 추출한다."""
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    info = data.get("info", {})
    raw_modality = data.get(
        "modality",
        info.get("type", "RT") if isinstance(info, dict) else "RT",
    )
    return str(raw_modality).strip().upper()


def build_qa_report(
    annotation_root: str | Path,
    taxonomy: TaxonomyConfig,
    *,
    modality: str | None = None,
) -> dict[str, Any]:
    """폴더의 JSON annotation을 전부 검증하고 집계 결과를 반환한다."""
    root = Path(annotation_root)
    if not root.is_dir():
        raise ParsingError(f"Annotation root must be an existing directory: {root}")

    files = sorted(
        (path for path in root.rglob("*.json") if path.is_file()),
        key=lambda path: path.relative_to(root).as_posix().lower(),
    )
    label_counts: Counter[str] = Counter()
    modality_counts: Counter[str] = Counter()
    errors: list[dict[str, str]] = []
    valid_files = 0
    annotation_count = 0

    normalized_modality = modality.strip().upper() if isinstance(modality, str) else None
    for path in files:
        relative_path = path.relative_to(root).as_posix()
        try:
            annotations = parse_riawelc_json(
                path,
                taxonomy,
                expected_modality=modality,
            )
        except (ParsingError, OSError, UnicodeError) as exc:
            errors.append({"file": relative_path, "error": str(exc)})
            continue

        valid_files += 1
        annotation_count += len(annotations)
        if annotations:
            modality_counts[annotations[0].modality] += 1
        else:
            # 빈 annotation 파일도 원본 JSON의 검사 방식을 modality 통계에 포함한다.
            modality_counts[
                normalized_modality or _read_validated_file_modality(path)
            ] += 1
        for annotation in annotations:
            label_counts[annotation.label_canonical] += 1

    return {
        "annotation_root": str(root),
        "modality": normalized_modality,
        "files_total": len(files),
        "files_valid": valid_files,
        "files_invalid": len(errors),
        "annotation_count": annotation_count,
        "label_counts": dict(sorted(label_counts.items())),
        "modality_counts": dict(sorted(modality_counts.items())),
        "errors": errors,
    }


def _build_parser() -> argparse.ArgumentParser:
    """Annotation 폴더 QA 리포트 CLI의 명령행 인자를 구성한다."""
    parser = argparse.ArgumentParser(
        description="Validate a RIAWELC annotation directory and write a QA report."
    )
    parser.add_argument("--annotations", required=True, type=Path)
    parser.add_argument(
        "--taxonomy",
        type=Path,
        help="Path to a custom taxonomy YAML (defaults to packaged canonical taxonomy)",
    )
    parser.add_argument("--modality", help="Require every JSON file to use this modality")
    parser.add_argument("--output", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    """입력 폴더를 검증하고 JSON 리포트를 기록하는 CLI 진입점."""
    args = _build_parser().parse_args(argv)
    try:
        taxonomy = (
            TaxonomyConfig.load_from_yaml(args.taxonomy)
            if args.taxonomy
            else TaxonomyConfig.load_default()
        )
        report = build_qa_report(args.annotations, taxonomy, modality=args.modality)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except (ParsingError, FileNotFoundError, OSError) as exc:
        print(f"error: {exc}")
        return 1

    print(json.dumps(report, ensure_ascii=False))
    return 1 if report["files_invalid"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
