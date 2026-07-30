from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import csv
import hashlib
import json
import re

from statebus.refs import TableCellLocator, TextSpanLocator


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
    # Most legacy corpus rows represent one metric cell.  Structured rows are
    # used by the bounded adaptive path so Projection can preserve every input
    # column and its table-cell locator without reparsing prompt text.
    metadata: dict[str, object] = field(default_factory=dict)

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
            ("ACME", "2025Q4"): FinancialReportDocument(
                ticker="ACME",
                quarter="2025Q4",
                source_doc_hash="sha256:doc-acme-2025q4",
                title="ACME 2025Q4 operating review",
                metadata_hints=("compare_metric", "revenue", "gross_margin", "operating_income", "quarterly"),
                text_fragments=(
                    CorpusTextFragment(
                        fragment_id="chunk-1",
                        source_doc_hash="sha256:doc-acme-2025q4",
                        text="Revenue for ACME in 2025Q4 reached a record level as year-end enterprise deals closed ahead of target.",
                        start_char=0,
                        end_char=99,
                    ),
                    CorpusTextFragment(
                        fragment_id="chunk-2",
                        source_doc_hash="sha256:doc-acme-2025q4",
                        text="Employee headcount increased 8% to 52000 as part of the ongoing go-to-market expansion strategy.",
                        start_char=100,
                        end_char=196,
                    ),
                    CorpusTextFragment(
                        fragment_id="chunk-3",
                        source_doc_hash="sha256:doc-acme-2025q4",
                        text="The board approved a new share buyback program of 500M targeting excess cash generated in H2 2025.",
                        start_char=197,
                        end_char=297,
                    ),
                    CorpusTextFragment(
                        fragment_id="chunk-4",
                        source_doc_hash="sha256:doc-acme-2025q4",
                        text="Gross margin remained stable despite higher services mix as product pricing held firm through renewals.",
                        start_char=298,
                        end_char=398,
                    ),
                ),
                table_rows=(
                    CorpusTableRow(
                        source_doc_hash="sha256:doc-acme-2025q4",
                        table_id="income",
                        sheet_name="income",
                        row_idx=1,
                        col_idx=1,
                        metric_name="revenue",
                        value="109",
                        rendered_text="Revenue = 109 for ACME 2025Q4.",
                    ),
                    CorpusTableRow(
                        source_doc_hash="sha256:doc-acme-2025q4",
                        table_id="income",
                        sheet_name="income",
                        row_idx=2,
                        col_idx=1,
                        metric_name="gross_margin",
                        value="36",
                        rendered_text="Gross margin = 36 for ACME 2025Q4.",
                    ),
                    CorpusTableRow(
                        source_doc_hash="sha256:doc-acme-2025q4",
                        table_id="income",
                        sheet_name="income",
                        row_idx=3,
                        col_idx=1,
                        metric_name="operating_income",
                        value="15",
                        rendered_text="Operating income = 15 for ACME 2025Q4.",
                    ),
                ),
            ),
            ("BETA", "2026Q1"): FinancialReportDocument(
                ticker="BETA",
                quarter="2026Q1",
                source_doc_hash="sha256:doc-beta-2026q1",
                title="BETA 2026Q1 quarterly earnings report",
                metadata_hints=("compare_metric", "revenue", "gross_margin", "operating_income", "quarterly"),
                text_fragments=(
                    CorpusTextFragment(
                        fragment_id="chunk-1",
                        source_doc_hash="sha256:doc-beta-2026q1",
                        text="BETA reported strong Q1 2026 results with revenue growth driven by cloud and subscription segments.",
                        start_char=0,
                        end_char=95,
                    ),
                    CorpusTextFragment(
                        fragment_id="chunk-2",
                        source_doc_hash="sha256:doc-beta-2026q1",
                        text="Product launches contributed to 40% of new customer acquisitions during the quarter.",
                        start_char=96,
                        end_char=178,
                    ),
                    CorpusTextFragment(
                        fragment_id="chunk-3",
                        source_doc_hash="sha256:doc-beta-2026q1",
                        text="BETA R&D investment grew to 12% of revenue reflecting accelerated investment in platform capabilities.",
                        start_char=179,
                        end_char=277,
                    ),
                    CorpusTextFragment(
                        fragment_id="chunk-4",
                        source_doc_hash="sha256:doc-beta-2026q1",
                        text="Gross margin expanded as subscription mix increased and hardware component costs declined quarter-on-quarter.",
                        start_char=278,
                        end_char=382,
                    ),
                ),
                table_rows=(
                    CorpusTableRow(
                        source_doc_hash="sha256:doc-beta-2026q1",
                        table_id="income",
                        sheet_name="income",
                        row_idx=1,
                        col_idx=1,
                        metric_name="revenue",
                        value="87",
                        rendered_text="Revenue = 87 for BETA 2026Q1.",
                    ),
                    CorpusTableRow(
                        source_doc_hash="sha256:doc-beta-2026q1",
                        table_id="income",
                        sheet_name="income",
                        row_idx=2,
                        col_idx=1,
                        metric_name="gross_margin",
                        value="31",
                        rendered_text="Gross margin = 31 for BETA 2026Q1.",
                    ),
                    CorpusTableRow(
                        source_doc_hash="sha256:doc-beta-2026q1",
                        table_id="income",
                        sheet_name="income",
                        row_idx=3,
                        col_idx=1,
                        metric_name="operating_income",
                        value="11",
                        rendered_text="Operating income = 11 for BETA 2026Q1.",
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


@dataclass(frozen=True)
class IncidentLogDocument:
    dataset_id: str
    log_path: str
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
class OfflineIncidentLogCorpus:
    _cache: dict[str, IncidentLogDocument] = field(default_factory=dict)

    @staticmethod
    def _source_doc_hash(path: Path) -> str:
        return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()

    @staticmethod
    def _load_text(path: str) -> str:
        if not path.strip():
            return ""
        resolved = Path(path)
        if not resolved.is_absolute():
            resolved = Path.cwd() / resolved
        if not resolved.exists() or not resolved.is_file():
            raise KeyError(f"offline incident corpus missing dataset path: {path}")
        return resolved.read_text(encoding="utf-8")

    @staticmethod
    def _boot_log_metrics(*, source_doc_hash: str, text: str) -> tuple[CorpusTableRow, ...]:
        ready_ts = 0.0
        storage_wait = 0.0
        service_name = "service"
        slow_phase = "storage_mount"
        root_cause = "unknown"
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        for line in lines:
            if "Starting " in line and ".service" in line:
                tail = line.split("Starting ", 1)[1]
                service_name = tail.split()[0].strip()
            match = re.search(r"Storage mounted \(([-+]?\d+(?:\.\d+)?)s wait\)", line)
            if match is not None:
                storage_wait = float(match.group(1))
            if "high IO wait detected" in line:
                root_cause = "high_io_wait"
            elif "Storage mounted" in line and root_cause == "unknown":
                root_cause = "normal_mount_wait"
            match = re.search(r"total startup:\s*([-+]?\d+(?:\.\d+)?)s", line)
            if match is not None:
                ready_ts = float(match.group(1))
        values = (
            ("service_name", service_name),
            ("slow_phase", slow_phase),
            ("wait_duration_seconds", f"{storage_wait:.1f}"),
            ("ready_seconds", f"{ready_ts:.1f}"),
            ("root_cause", root_cause),
        )
        return tuple(
            CorpusTableRow(
                source_doc_hash=source_doc_hash,
                table_id="incident_boot_metrics",
                sheet_name="boot_log",
                row_idx=index,
                col_idx=1,
                metric_name=metric_name,
                value=value,
                rendered_text=f"{metric_name} = {value}.",
                extractor_version="incident-boot-log-v1",
            )
            for index, (metric_name, value) in enumerate(values, start=1)
        )

    @staticmethod
    def _text_fragments(*, source_doc_hash: str, log_text: str, journal_text: str) -> tuple[CorpusTextFragment, ...]:
        fragments: list[CorpusTextFragment] = []
        cursor = 0
        for index, line in enumerate([line.strip() for line in log_text.splitlines() if line.strip()], start=1):
            start_char = cursor
            end_char = start_char + len(line)
            cursor = end_char + 1
            fragments.append(
                CorpusTextFragment(
                    fragment_id=f"boot-{index}",
                    source_doc_hash=source_doc_hash,
                    text=line,
                    start_char=start_char,
                    end_char=end_char,
                    extractor_version="incident-boot-line-v1",
                )
            )
        if journal_text.strip():
            journal_base = cursor
            for index, line in enumerate([line.strip() for line in journal_text.splitlines() if line.strip()], start=1):
                start_char = journal_base
                end_char = start_char + len(line)
                journal_base = end_char + 1
                fragments.append(
                    CorpusTextFragment(
                        fragment_id=f"journal-{index}",
                        source_doc_hash=source_doc_hash,
                        text=line,
                        start_char=start_char,
                        end_char=end_char,
                        extractor_version="incident-journal-line-v1",
                    )
                )
        return tuple(fragments)

    def resolve(
        self,
        *,
        dataset_id: str,
        log_path: str,
        journal_path: str = "",
        service_name: str = "",
    ) -> IncidentLogDocument:
        if not log_path.strip():
            raise KeyError(f"offline incident corpus missing log_path for {dataset_id}")
        cache_key = json.dumps(
            {
                "dataset_id": dataset_id,
                "log_path": log_path,
                "journal_path": journal_path,
                "service_name": service_name,
            },
            ensure_ascii=True,
            sort_keys=True,
        )
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached
        resolved_log_path = Path(log_path)
        if not resolved_log_path.is_absolute():
            resolved_log_path = Path.cwd() / resolved_log_path
        if not resolved_log_path.exists() or not resolved_log_path.is_file():
            raise KeyError(f"offline incident corpus missing dataset path for {dataset_id}: {log_path}")
        log_text = resolved_log_path.read_text(encoding="utf-8")
        journal_text = self._load_text(journal_path)
        source_doc_hash = self._source_doc_hash(resolved_log_path)
        document = IncidentLogDocument(
            dataset_id=dataset_id,
            log_path=str(resolved_log_path),
            source_doc_hash=source_doc_hash,
            title=service_name or resolved_log_path.stem,
            metadata_hints=(
                dataset_id,
                service_name or resolved_log_path.stem,
                "startup_latency",
                "storage_mount",
                "high_io_wait",
            ),
            text_fragments=self._text_fragments(
                source_doc_hash=source_doc_hash,
                log_text=log_text,
                journal_text=journal_text,
            ),
            table_rows=self._boot_log_metrics(source_doc_hash=source_doc_hash, text=log_text),
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
    def _cross_period_revenue_rows(
        *,
        source_doc_hash: str,
        text: str,
    ) -> tuple[CorpusTableRow, ...]:
        rows: list[CorpusTableRow] = []
        matches = re.finditer(
            r"(?ms)^## ([^\n]+? Revenue Table)\s*(.*?)(?=^## |\Z)",
            text,
        )
        for match in matches:
            title = match.group(1).strip()
            section_text = match.group(2)
            ticker = title.removesuffix("Revenue Table").strip().upper()
            if not ticker:
                continue
            data_row_idx = 0
            for line in section_text.splitlines():
                stripped = line.strip()
                if not stripped.startswith("|"):
                    continue
                cells = [cell.strip() for cell in stripped.strip("|").split("|")]
                if len(cells) < 2:
                    continue
                quarter = cells[0]
                if quarter in {"quarter", "---"} or set(quarter) == {"-"}:
                    continue
                data_row_idx += 1
                value = cells[1]
                rows.append(
                    CorpusTableRow(
                        source_doc_hash=source_doc_hash,
                        table_id=f"{ticker.lower()}_revenue",
                        sheet_name="markdown",
                        row_idx=data_row_idx,
                        col_idx=1,
                        metric_name="revenue",
                        value=value,
                        rendered_text=f"Revenue = {value} for {ticker} {quarter}.",
                        extractor_version="markdown-cross-period-v1",
                    )
                )
        return tuple(rows)

    @staticmethod
    def _generic_table_rows(
        *,
        source_doc_hash: str,
        text: str,
    ) -> tuple[CorpusTableRow, ...]:
        """Parse small repo-local markdown tables as typed evidence rows.

        The established five-column operating-metric parser above stays the
        compatibility path. This narrower generic parser serves bounded
        aggregation/anomaly tasks whose rows carry a group field or a metric
        other than revenue. It accepts only plain scalar cells and supports a
        two-column period/value table where the value header identifies the
        metric; cross-period ticker rows are retained separately below.
        """
        rows: list[CorpusTableRow] = []
        lines = text.splitlines()
        table_index = 0
        index = 0
        while index + 2 < len(lines):
            header_line = lines[index].strip()
            divider_line = lines[index + 1].strip()
            if not header_line.startswith("|") or not divider_line.startswith("|"):
                index += 1
                continue
            headers = [cell.strip().lower().replace(" ", "_") for cell in header_line.strip("|").split("|")]
            divider = [cell.strip() for cell in divider_line.strip("|").split("|")]
            if (
                len(headers) < 2
                or len(headers) != len(divider)
                or any(not cell or set(cell) - {"-", ":"} for cell in divider)
            ):
                index += 1
                continue
            table_index += 1
            row_index = 0
            index += 2
            while index < len(lines) and lines[index].strip().startswith("|"):
                cells = [cell.strip() for cell in lines[index].strip().strip("|").split("|")]
                if len(cells) != len(headers):
                    break
                structured_row = {
                    header: OfflineMarkdownLongDocCorpus._parse_scalar(cell)
                    for header, cell in zip(headers, cells, strict=True)
                }
                numeric_fields = [
                    key
                    for key, value in structured_row.items()
                    if isinstance(value, (int, float)) and not isinstance(value, bool)
                ]
                if numeric_fields:
                    metric_name = numeric_fields[0]
                    row_index += 1
                    rows.append(CorpusTableRow(
                        source_doc_hash=source_doc_hash,
                        table_id=f"markdown_table_{table_index}",
                        sheet_name="markdown",
                        row_idx=row_index,
                        col_idx=headers.index(metric_name) + 1,
                        metric_name=metric_name,
                        value=str(structured_row[metric_name]),
                        rendered_text=json.dumps(structured_row, sort_keys=True, separators=(",", ":")),
                        extractor_version="markdown-structured-table-v1",
                        metadata={"structured_row": structured_row},
                    ))
                index += 1
        return tuple(rows)

    @staticmethod
    def _parse_scalar(value: str) -> object:
        normalized = value.strip()
        if re.fullmatch(r"-?(?:\d+(?:\.\d*)?|\.\d+)", normalized):
            return float(normalized)
        return normalized

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
        if not table_rows:
            generic_rows = self._generic_table_rows(source_doc_hash=source_doc_hash, text=text)
            cross_period_rows = self._cross_period_revenue_rows(source_doc_hash=source_doc_hash, text=text)
            # Generic rows keep every column for bounded projection. The
            # established cross-period rows retain ticker identity for the
            # legacy financial-analysis family, which selects metric="revenue".
            table_rows = generic_rows + cross_period_rows
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
