from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import csv
import hashlib
import re

from v2.refs import TableCellLocator, TextSpanLocator


@dataclass(frozen=True)
class CorpusTextFragment:
    fragment_id: str
    source_doc_hash: str
    text: str
    start_char: int
    end_char: int
    extractor_version: str = "chunker-v1"

    def locator(self) -> TextSpanLocator:
        return TextSpanLocator(
            source_doc_hash=self.source_doc_hash,
            canonical_text_id=self.fragment_id,
            start_char=self.start_char,
            end_char=self.end_char,
            extractor_version=self.extractor_version,
        )


@dataclass(frozen=True)
class CorpusTableRow:
    source_doc_hash: str
    table_id: str
    sheet_name: str
    row_idx: int
    col_idx: int
    metric_name: str
    value: str
    rendered_text: str
    extractor_version: str = "table-v1"

    def locator(self) -> TableCellLocator:
        return TableCellLocator(
            source_doc_hash=self.source_doc_hash,
            table_id=self.table_id,
            sheet_name=self.sheet_name,
            row_idx=self.row_idx,
            col_idx=self.col_idx,
            extractor_version=self.extractor_version,
        )


@dataclass(frozen=True)
class FinancialReportDocument:
    ticker: str
    quarter: str
    source_doc_hash: str
    title: str
    metadata_hints: tuple[str, ...]
    text_fragments: tuple[CorpusTextFragment, ...]
    table_rows: tuple[CorpusTableRow, ...]

    @property
    def full_corpus_bytes(self) -> int:
        return sum(len(fragment.text.encode("utf-8")) for fragment in self.text_fragments) + sum(
            len(row.rendered_text.encode("utf-8")) for row in self.table_rows
        )


@dataclass
class OfflineFinancialReportCorpus:
    documents: dict[tuple[str, str], FinancialReportDocument] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.documents:
            return
        self.documents = {
            ("ACME", "2026Q1"): FinancialReportDocument(
                ticker="ACME",
                quarter="2026Q1",
                source_doc_hash="sha256:doc-acme-2026q1",
                title="ACME 2026Q1 operating review",
                metadata_hints=("compare_metric", "revenue", "gross_margin", "operating_income", "quarterly"),
                text_fragments=(
                    CorpusTextFragment(
                        fragment_id="chunk-1",
                        source_doc_hash="sha256:doc-acme-2026q1",
                        text="Revenue increased for ACME in 2026Q1 as enterprise demand improved in APAC.",
                        start_char=0,
                        end_char=80,
                    ),
                    CorpusTextFragment(
                        fragment_id="chunk-2",
                        source_doc_hash="sha256:doc-acme-2026q1",
                        text="Gross margin held steady while services backlog expanded across existing accounts.",
                        start_char=81,
                        end_char=162,
                    ),
                    CorpusTextFragment(
                        fragment_id="chunk-3",
                        source_doc_hash="sha256:doc-acme-2026q1",
                        text="Management highlighted stronger enterprise renewals, improved APAC channel sell-through, and stable collections.",
                        start_char=163,
                        end_char=274,
                    ),
                    CorpusTextFragment(
                        fragment_id="chunk-4",
                        source_doc_hash="sha256:doc-acme-2026q1",
                        text="Operating expense discipline offset hiring in go-to-market teams while services utilization remained healthy.",
                        start_char=275,
                        end_char=385,
                    ),
                ),
                table_rows=(
                    CorpusTableRow(
                        source_doc_hash="sha256:doc-acme-2026q1",
                        table_id="income",
                        sheet_name="income",
                        row_idx=1,
                        col_idx=1,
                        metric_name="revenue",
                        value="120",
                        rendered_text="Revenue = 120 for ACME 2026Q1.",
                    ),
                    CorpusTableRow(
                        source_doc_hash="sha256:doc-acme-2026q1",
                        table_id="income",
                        sheet_name="income",
                        row_idx=2,
                        col_idx=1,
                        metric_name="gross_margin",
                        value="38",
                        rendered_text="Gross margin = 38 for ACME 2026Q1.",
                    ),
                    CorpusTableRow(
                        source_doc_hash="sha256:doc-acme-2026q1",
                        table_id="income",
                        sheet_name="income",
                        row_idx=3,
                        col_idx=1,
                        metric_name="operating_income",
                        value="19",
                        rendered_text="Operating income = 19 for ACME 2026Q1.",
                    ),
                ),
            ),
            ("ACME", "2026Q2"): FinancialReportDocument(
                ticker="ACME",
                quarter="2026Q2",
                source_doc_hash="sha256:doc-acme-2026q2",
                title="ACME 2026Q2 operating review",
                metadata_hints=("compare_metric", "revenue", "gross_margin", "operating_income", "quarterly"),
                text_fragments=(
                    CorpusTextFragment(
                        fragment_id="chunk-1",
                        source_doc_hash="sha256:doc-acme-2026q2",
                        text="Revenue increased for ACME in 2026Q2 as renewals and product mix both improved.",
                        start_char=0,
                        end_char=84,
                    ),
                    CorpusTextFragment(
                        fragment_id="chunk-2",
                        source_doc_hash="sha256:doc-acme-2026q2",
                        text="Management noted stronger pipeline conversion and stable service attach rates.",
                        start_char=85,
                        end_char=163,
                    ),
                    CorpusTextFragment(
                        fragment_id="chunk-3",
                        source_doc_hash="sha256:doc-acme-2026q2",
                        text="The company cited improved commercial pricing and better conversion of backlog into recognized revenue.",
                        start_char=164,
                        end_char=270,
                    ),
                    CorpusTextFragment(
                        fragment_id="chunk-4",
                        source_doc_hash="sha256:doc-acme-2026q2",
                        text="Services attach remained stable while support renewal rates improved across strategic accounts.",
                        start_char=271,
                        end_char=369,
                    ),
                ),
                table_rows=(
                    CorpusTableRow(
                        source_doc_hash="sha256:doc-acme-2026q2",
                        table_id="income",
                        sheet_name="income",
                        row_idx=1,
                        col_idx=1,
                        metric_name="revenue",
                        value="132",
                        rendered_text="Revenue = 132 for ACME 2026Q2.",
                    ),
                    CorpusTableRow(
                        source_doc_hash="sha256:doc-acme-2026q2",
                        table_id="income",
                        sheet_name="income",
                        row_idx=2,
                        col_idx=1,
                        metric_name="gross_margin",
                        value="39",
                        rendered_text="Gross margin = 39 for ACME 2026Q2.",
                    ),
                    CorpusTableRow(
                        source_doc_hash="sha256:doc-acme-2026q2",
                        table_id="income",
                        sheet_name="income",
                        row_idx=3,
                        col_idx=1,
                        metric_name="operating_income",
                        value="23",
                        rendered_text="Operating income = 23 for ACME 2026Q2.",
                    ),
                ),
            ),
            ("ACME", "2026Q3"): FinancialReportDocument(
                ticker="ACME",
                quarter="2026Q3",
                source_doc_hash="sha256:doc-acme-2026q3",
                title="ACME 2026Q3 operating review",
                metadata_hints=("compare_metric", "revenue", "gross_margin", "operating_income", "quarterly"),
                text_fragments=(
                    CorpusTextFragment(
                        fragment_id="chunk-1",
                        source_doc_hash="sha256:doc-acme-2026q3",
                        text="Revenue increased again in 2026Q3 as enterprise upgrades and partner channels both expanded.",
                        start_char=0,
                        end_char=96,
                    ),
                    CorpusTextFragment(
                        fragment_id="chunk-2",
                        source_doc_hash="sha256:doc-acme-2026q3",
                        text="Gross margin improved on better product mix while support cost inflation remained contained.",
                        start_char=97,
                        end_char=190,
                    ),
                    CorpusTextFragment(
                        fragment_id="chunk-3",
                        source_doc_hash="sha256:doc-acme-2026q3",
                        text="Management described stronger EMEA pipeline conversion and continued APAC expansion in large accounts.",
                        start_char=191,
                        end_char=297,
                    ),
                    CorpusTextFragment(
                        fragment_id="chunk-4",
                        source_doc_hash="sha256:doc-acme-2026q3",
                        text="Operating leverage improved as revenue growth outpaced incremental sales and marketing expense.",
                        start_char=298,
                        end_char=396,
                    ),
                ),
                table_rows=(
                    CorpusTableRow(
                        source_doc_hash="sha256:doc-acme-2026q3",
                        table_id="income",
                        sheet_name="income",
                        row_idx=1,
                        col_idx=1,
                        metric_name="revenue",
                        value="145",
                        rendered_text="Revenue = 145 for ACME 2026Q3.",
                    ),
                    CorpusTableRow(
                        source_doc_hash="sha256:doc-acme-2026q3",
                        table_id="income",
                        sheet_name="income",
                        row_idx=2,
                        col_idx=1,
                        metric_name="gross_margin",
                        value="41",
                        rendered_text="Gross margin = 41 for ACME 2026Q3.",
                    ),
                    CorpusTableRow(
                        source_doc_hash="sha256:doc-acme-2026q3",
                        table_id="income",
                        sheet_name="income",
                        row_idx=3,
                        col_idx=1,
                        metric_name="operating_income",
                        value="27",
                        rendered_text="Operating income = 27 for ACME 2026Q3.",
                    ),
                ),
            ),
        }

    def resolve(self, *, ticker: str, quarter: str) -> FinancialReportDocument:
        key = (ticker.upper(), quarter.upper())
        if key not in self.documents:
            raise KeyError(f"offline corpus missing document for {key[0]} {key[1]}")
        return self.documents[key]


@dataclass(frozen=True)
class CsvTableDocument:
    dataset_id: str
    csv_path: str
    source_doc_hash: str
    title: str
    metadata_hints: tuple[str, ...]
    text_fragments: tuple[CorpusTextFragment, ...]
    table_rows: tuple[CorpusTableRow, ...]

    @property
    def full_corpus_bytes(self) -> int:
        return sum(len(fragment.text.encode("utf-8")) for fragment in self.text_fragments) + sum(
            len(row.rendered_text.encode("utf-8")) for row in self.table_rows
        )


@dataclass
class OfflineCsvTableCorpus:
    _cache: dict[str, CsvTableDocument] = field(default_factory=dict)

    def resolve(self, *, dataset_id: str, csv_path: str) -> CsvTableDocument:
        if not csv_path.strip():
            raise KeyError(f"offline csv corpus missing csv_path for {dataset_id}")
        cache_key = f"{dataset_id}:{csv_path}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached
        path = Path(csv_path)
        if not path.is_absolute():
            path = Path.cwd() / path
        if not path.exists():
            raise KeyError(f"offline csv corpus missing dataset path for {dataset_id}: {csv_path}")
        if not path.is_file():
            raise KeyError(f"offline csv corpus dataset path is not a file for {dataset_id}: {csv_path}")
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            rows = list(reader)
            fieldnames = tuple(reader.fieldnames or ())
        preview_rows = rows[: min(len(rows), 8)]
        text_fragments = tuple(
            CorpusTextFragment(
                fragment_id=f"{dataset_id}-preview-{index + 1}",
                source_doc_hash=f"sha256:csv-{dataset_id}",
                text=" | ".join(f"{key}={value}" for key, value in row.items()),
                start_char=index * 100,
                end_char=index * 100 + len(" | ".join(f"{key}={value}" for key, value in row.items())),
                extractor_version="csv-preview-v1",
            )
            for index, row in enumerate(preview_rows)
        )
        table_rows = tuple(
            CorpusTableRow(
                source_doc_hash=f"sha256:csv-{dataset_id}",
                table_id=dataset_id,
                sheet_name="csv",
                row_idx=index + 1,
                col_idx=1,
                metric_name=column,
                value=str(row.get(column, "")),
                rendered_text=f"{column} = {row.get(column, '')} for {dataset_id} row {index + 1}.",
                extractor_version="csv-cell-v1",
            )
            for index, row in enumerate(preview_rows)
            for column in fieldnames[: min(len(fieldnames), 6)]
        )
        document = CsvTableDocument(
            dataset_id=dataset_id,
            csv_path=str(path),
            source_doc_hash=f"sha256:csv-{dataset_id}",
            title=f"{dataset_id} csv preview",
            metadata_hints=(
                dataset_id,
                path.name,
                *fieldnames[: min(len(fieldnames), 6)],
            ),
            text_fragments=text_fragments,
            table_rows=table_rows,
        )
        self._cache[cache_key] = document
        return document


@dataclass
class OfflineMarkdownLongDocCorpus:
    _cache: dict[str, FinancialReportDocument] = field(default_factory=dict)

    @staticmethod
    def _source_doc_hash(path: Path) -> str:
        return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()

    @staticmethod
    def _metric_table_rows(
        *,
        source_doc_hash: str,
        section_text: str,
    ) -> tuple[CorpusTableRow, ...]:
        rows: list[CorpusTableRow] = []
        for row_idx, line in enumerate(section_text.splitlines(), start=1):
            stripped = line.strip()
            if not stripped.startswith("|"):
                continue
            cells = [cell.strip() for cell in stripped.strip("|").split("|")]
            if row_idx <= 2 or len(cells) < 6 or cells[0] == "---":
                continue
            quarter = cells[0]
            metric_names = (
                "revenue_musd",
                "gross_margin_pct",
                "operating_expense_musd",
                "churn_rate_pct",
                "on_time_delivery_pct",
            )
            for col_idx, metric_name in enumerate(metric_names, start=1):
                value = cells[col_idx]
                rows.append(
                    CorpusTableRow(
                        source_doc_hash=source_doc_hash,
                        table_id="metric_table",
                        sheet_name="markdown",
                        row_idx=row_idx - 2,
                        col_idx=col_idx,
                        metric_name=f"{metric_name}:{quarter}",
                        value=value,
                        rendered_text=f"{metric_name} = {value} for {quarter}.",
                        extractor_version="markdown-table-v1",
                    )
                )
        return tuple(rows)

    @staticmethod
    def _text_fragments(
        *,
        source_doc_hash: str,
        text: str,
    ) -> tuple[CorpusTextFragment, ...]:
        fragments: list[CorpusTextFragment] = []
        cursor = 0
        sections = re.split(r"(?m)^## ", text)
        for index, section in enumerate(section for section in sections if section.strip()):
            normalized = section.strip()
            start_char = text.find(normalized, cursor)
            if start_char < 0:
                start_char = cursor
            end_char = start_char + len(normalized)
            cursor = end_char
            fragments.append(
                CorpusTextFragment(
                    fragment_id=f"section-{index + 1}",
                    source_doc_hash=source_doc_hash,
                    text=normalized,
                    start_char=start_char,
                    end_char=end_char,
                    extractor_version="markdown-section-v1",
                )
            )
        return tuple(fragments)

    def resolve(self, *, dataset_id: str, document_path: str) -> FinancialReportDocument:
        if not document_path.strip():
            raise KeyError(f"offline markdown corpus missing document_path for {dataset_id}")
        cache_key = f"{dataset_id}:{document_path}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached
        path = Path(document_path)
        if not path.is_absolute():
            path = Path.cwd() / path
        if not path.exists() or not path.is_file():
            raise KeyError(f"offline markdown corpus missing dataset path for {dataset_id}: {document_path}")
        text = path.read_text(encoding="utf-8")
        source_doc_hash = self._source_doc_hash(path)
        fragments = self._text_fragments(source_doc_hash=source_doc_hash, text=text)
        metric_table_match = re.search(
            r"(?ms)^## Metric Table\s*(.*?)^\s*## ",
            text + "\n## END\n",
        )
        metric_section = metric_table_match.group(1) if metric_table_match else ""
        table_rows = self._metric_table_rows(source_doc_hash=source_doc_hash, section_text=metric_section)
        title_match = re.search(r"(?m)^# (.+)$", text)
        title = title_match.group(1).strip() if title_match else f"{dataset_id} markdown report"
        metadata_hints = (
            dataset_id,
            path.name,
            "long_doc_table",
            "metric_table",
            "churn",
            "supply_chain",
        )
        document = FinancialReportDocument(
            ticker=dataset_id.upper(),
            quarter="2026Q3",
            source_doc_hash=source_doc_hash,
            title=title,
            metadata_hints=metadata_hints,
            text_fragments=fragments,
            table_rows=table_rows,
        )
        self._cache[cache_key] = document
        return document
