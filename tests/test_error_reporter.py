"""
ErrorReport 與 SilverProcessor return_report 整合測試

覆蓋目標：核心邏輯 ≥ 85%
- ErrorReport：has_errors / to_dataframe / to_excel / summary 所有分支
- SilverProcessor.process(return_report=True)：clean / cast fail / CB trip 三路徑
- MetadataBuilder.build(return_report=True)：傳遞與回傳正確性
"""

import pytest
import pandas as pd
from pathlib import Path
from unittest.mock import MagicMock, patch

from seafin_metadata_builder.reporter import ErrorReport, CastFailureDetail
from seafin_metadata_builder.validation.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerResult,
)
from seafin_metadata_builder.processors.silver import SilverProcessor
from seafin_metadata_builder.config import SchemaConfig, ColumnSpec
from seafin_metadata_builder.builder import MetadataBuilder
from seafin_metadata_builder.exceptions import CircuitBreakerError


# ---------------------------------------------------------------------------
# 輔助工具
# ---------------------------------------------------------------------------

def _make_tripped_cb_result(col: str = "amount") -> CircuitBreakerResult:
    """建立已觸發的 CircuitBreakerResult。"""
    return CircuitBreakerResult(
        status="TRIPPED",
        null_ratios={col: 0.6},
        tripped_columns=[col],
        threshold=0.3,
        message="Circuit breaker tripped",
    )


def _make_ok_cb_result() -> CircuitBreakerResult:
    """建立未觸發的 CircuitBreakerResult。"""
    return CircuitBreakerResult(
        status="OK",
        null_ratios={"amount": 0.01},
        tripped_columns=[],
        threshold=0.3,
        message="OK",
    )


def _make_report(
    *,
    cast_failures: list[CastFailureDetail] | None = None,
    cb_result: CircuitBreakerResult | None = None,
) -> ErrorReport:
    """建立測試用 ErrorReport。"""
    failures = cast_failures or []
    summary = {}
    for f in failures:
        summary[f.column] = summary.get(f.column, 0) + 1
    return ErrorReport(
        cast_failures=failures,
        cast_summary=summary,
        circuit_breaker_result=cb_result,
        total_rows=100,
    )


def _make_schema(*cols: tuple[str, str]) -> SchemaConfig:
    """
    快速建立 SchemaConfig。
    cols: [(target, dtype), ...]，source 與 target 同名。
    """
    return SchemaConfig(
        columns=[
            ColumnSpec(source=t, target=t, dtype=d)
            for t, d in cols
        ],
        circuit_breaker_threshold=0.3,
    )


def _string_df(**kwargs) -> pd.DataFrame:
    """建立 StringDtype DataFrame，模擬 Bronze 輸出。"""
    return pd.DataFrame(
        {k: pd.array(v, dtype="string") for k, v in kwargs.items()}
    )


# ---------------------------------------------------------------------------
# ErrorReport.has_errors
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestErrorReportHasErrors:

    def test_has_errors_with_cast_failures(self):
        """有 cast 失敗 → has_errors=True。"""
        report = _make_report(
            cast_failures=[CastFailureDetail(0, "amount", "一百元")]
        )
        assert report.has_errors is True

    def test_has_errors_with_circuit_breaker_tripped(self):
        """CB 觸發 → has_errors=True。"""
        report = _make_report(cb_result=_make_tripped_cb_result())
        assert report.has_errors is True

    def test_has_no_errors(self):
        """無失敗且 CB 未觸發 → has_errors=False。"""
        report = _make_report(cb_result=_make_ok_cb_result())
        assert report.has_errors is False

    def test_has_no_errors_when_cb_none(self):
        """無失敗且 CB=None → has_errors=False。"""
        report = _make_report()
        assert report.has_errors is False


# ---------------------------------------------------------------------------
# ErrorReport.to_dataframe
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestErrorReportToDataFrame:

    def test_to_dataframe_columns(self):
        """to_dataframe() 包含四個必要欄位。"""
        report = _make_report(
            cast_failures=[CastFailureDetail(5, "amount", "一百元")]
        )
        df = report.to_dataframe()
        assert set(df.columns) == {"row_index", "column", "original_value", "issue_type"}

    def test_to_dataframe_cast_failure_row(self):
        """cast failure 行的 issue_type 為 CAST_FAILURE，值正確。"""
        report = _make_report(
            cast_failures=[CastFailureDetail(5, "amount", "一百元")]
        )
        df = report.to_dataframe()
        row = df[df["column"] == "amount"].iloc[0]
        assert row["row_index"] == 5
        assert row["original_value"] == "一百元"
        assert row["issue_type"] == "CAST_FAILURE"

    def test_to_dataframe_circuit_breaker_row(self):
        """CB 觸發時 to_dataframe() 包含 CIRCUIT_BREAKER 行。"""
        report = _make_report(cb_result=_make_tripped_cb_result("amount"))
        df = report.to_dataframe()
        cb_rows = df[df["issue_type"] == "CIRCUIT_BREAKER"]
        assert len(cb_rows) == 1
        assert cb_rows.iloc[0]["column"] == "amount"

    def test_to_dataframe_empty(self):
        """無失敗時回傳空 DataFrame 但含欄位標題。"""
        report = _make_report()
        df = report.to_dataframe()
        assert len(df) == 0
        assert "row_index" in df.columns


# ---------------------------------------------------------------------------
# ErrorReport.to_excel
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestErrorReportToExcel:

    def test_to_excel_creates_file(self, tmp_path):
        """to_excel() 建立 Excel 檔案。"""
        report = _make_report(
            cast_failures=[CastFailureDetail(5, "amount", "一百元")],
        )
        out = tmp_path / "report.xlsx"
        report.to_excel(out)
        assert out.exists()

    def test_to_excel_has_summary_and_detail_sheets(self, tmp_path):
        """Excel 包含 Summary 與 Detail 兩個 sheet。"""
        report = _make_report(
            cast_failures=[CastFailureDetail(5, "amount", "一百元")],
        )
        out = tmp_path / "report.xlsx"
        report.to_excel(out)

        sheets = pd.ExcelFile(out).sheet_names
        assert "Summary" in sheets
        assert "Detail" in sheets

    def test_to_excel_creates_parent_dirs(self, tmp_path):
        """父目錄不存在時自動建立。"""
        report = _make_report()
        out = tmp_path / "nested" / "dir" / "report.xlsx"
        report.to_excel(out)
        assert out.exists()

    def test_to_excel_summary_contains_cast_column(self, tmp_path):
        """Summary sheet 包含 cast failure 欄位資訊。"""
        report = _make_report(
            cast_failures=[CastFailureDetail(5, "amount", "一百元")],
        )
        out = tmp_path / "report.xlsx"
        report.to_excel(out)

        df_summary = pd.read_excel(out, sheet_name="Summary")
        assert "amount" in df_summary["欄位"].values


# ---------------------------------------------------------------------------
# ErrorReport.summary
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestErrorReportSummary:

    def test_summary_contains_cast_info(self):
        """summary() 包含 cast failure 欄位名稱。"""
        report = _make_report(
            cast_failures=[CastFailureDetail(5, "amount", "一百元")]
        )
        text = report.summary()
        assert "amount" in text
        assert "轉換失敗" in text

    def test_summary_contains_cb_info(self):
        """summary() 包含 CircuitBreaker 狀態。"""
        report = _make_report(cb_result=_make_tripped_cb_result("amount"))
        text = report.summary()
        assert "CircuitBreaker" in text
        assert "TRIPPED" in text

    def test_summary_cb_not_executed(self):
        """CB=None 時 summary 說明未執行。"""
        report = _make_report()
        text = report.summary()
        assert "未執行" in text


# ---------------------------------------------------------------------------
# SilverProcessor.process(return_report=True)
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestSilverProcessorReturnReport:

    def setup_method(self):
        self.processor = SilverProcessor()

    def _process(self, df: pd.DataFrame, schema: SchemaConfig, **kwargs):
        return self.processor.process(df, schema, **kwargs)

    def test_silver_return_report_clean_data(self):
        """乾淨資料 → (df, report)，has_errors=False。"""
        df = _string_df(amount=["100", "200", "300"])
        schema = _make_schema(("amount", "BIGINT"))

        result = self._process(df, schema, return_report=True)
        assert isinstance(result, tuple)
        df_out, report = result
        assert len(df_out) == 3
        assert report.has_errors is False
        assert isinstance(report, ErrorReport)

    def test_silver_return_report_cast_failures(self):
        """含無效值 → report.cast_failures 記錄原始值。"""
        df = _string_df(amount=["100", "一百元", "300", "N/A"])
        schema = _make_schema(("amount", "BIGINT"))

        _, report = self._process(df, schema, return_report=True)
        assert len(report.cast_failures) > 0
        original_vals = [f.original_value for f in report.cast_failures]
        assert "一百元" in original_vals

    def test_silver_return_report_cast_failure_row_index(self):
        """cast failure 的 row_index 對應原始行號。"""
        df = _string_df(amount=["100", "bad_value", "300"])
        schema = _make_schema(("amount", "BIGINT"))

        _, report = self._process(df, schema, return_report=True)
        fail_indices = [f.row_index for f in report.cast_failures]
        assert 1 in fail_indices  # "bad_value" 在 index=1

    def test_silver_return_report_cb_tripped_no_exception(self):
        """CB 觸發時不拋出 exception，結果存入 report。"""
        # filter_empty_rows=False 才能讓 NULL 行留在 df 中被 CB 偵測
        many_nulls = ["100"] * 1 + [None] * 9  # 90% null
        df = _string_df(amount=many_nulls)
        schema = SchemaConfig(
            columns=[ColumnSpec(source="amount", target="amount", dtype="BIGINT")],
            circuit_breaker_threshold=0.3,
            filter_empty_rows=False,
        )

        # 不應拋出 CircuitBreakerError
        df_out, report = self._process(df, schema, return_report=True)
        assert report.circuit_breaker_result is not None
        assert report.circuit_breaker_result.is_tripped is True
        assert report.has_errors is True

    def test_silver_default_behavior_unchanged(self):
        """return_report=False（預設）→ 行為與原先完全一致，回傳純 DataFrame。"""
        df = _string_df(amount=["100", "200", "300"])
        schema = _make_schema(("amount", "BIGINT"))

        result = self._process(df, schema)
        assert isinstance(result, pd.DataFrame)
        assert not isinstance(result, tuple)

    def test_silver_default_raises_on_cb_trip(self):
        """return_report=False 時，CB 觸發仍應拋出 CircuitBreakerError。"""
        many_nulls = ["100"] + [None] * 9
        df = _string_df(amount=many_nulls)
        schema = SchemaConfig(
            columns=[ColumnSpec(source="amount", target="amount", dtype="BIGINT")],
            circuit_breaker_threshold=0.3,
            filter_empty_rows=False,  # 保留 NULL 行讓 CB 偵測
        )

        with pytest.raises(CircuitBreakerError):
            self._process(df, schema)

    def test_silver_return_report_cast_summary_populated(self):
        """report.cast_summary 包含各欄位失敗筆數。"""
        df = _string_df(amount=["100", "bad1", "bad2"])
        schema = _make_schema(("amount", "BIGINT"))

        _, report = self._process(df, schema, return_report=True)
        assert "amount" in report.cast_summary
        assert report.cast_summary["amount"] == 2


# ---------------------------------------------------------------------------
# MetadataBuilder.build(return_report=True)
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestBuilderReturnReport:

    def test_builder_return_report_propagates(self):
        """MetadataBuilder.build(return_report=True) 回傳 (df, ErrorReport) tuple。"""
        builder = MetadataBuilder()
        df_bronze = _string_df(amount=["100", "bad_value", "300"])

        schema = _make_schema(("amount", "BIGINT"))

        # Mock extract 直接回傳 df_bronze（跳過檔案讀取）
        with patch.object(builder, "extract", return_value=df_bronze):
            result = builder.build("fake.xlsx", schema, return_report=True)

        assert isinstance(result, tuple)
        df_out, report = result
        assert isinstance(df_out, pd.DataFrame)
        assert isinstance(report, ErrorReport)
        assert len(report.cast_failures) > 0

    def test_builder_default_returns_dataframe(self):
        """MetadataBuilder.build() 預設仍回傳純 DataFrame。"""
        builder = MetadataBuilder()
        df_bronze = _string_df(amount=["100", "200"])
        schema = _make_schema(("amount", "BIGINT"))

        with patch.object(builder, "extract", return_value=df_bronze):
            result = builder.build("fake.xlsx", schema)

        assert isinstance(result, pd.DataFrame)
        assert not isinstance(result, tuple)
