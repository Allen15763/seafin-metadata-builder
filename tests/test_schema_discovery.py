"""
SchemaDiscovery 單元測試

覆蓋目標：核心邏輯 ≥ 85%
- SchemaDiscovery._infer_column()：6 型別分支、空值率、全空欄位
- SchemaDiscovery._try_infer_dtype()：6 型別推斷路徑
- SchemaDraft.to_yaml()：正常輸出、父目錄自動建立、pyyaml 未安裝
- SchemaDraft.to_schema_config()：回傳正確 SchemaConfig
- SchemaDraft.summary()：包含必要資訊
"""

import sys
import pytest
import pandas as pd
from pathlib import Path
from unittest.mock import patch

from seafin_metadata_builder.discovery import (
    SchemaDiscovery,
    SchemaDraft,
    ColumnInferenceResult,
    _normalize_column_name,
)
from seafin_metadata_builder import SchemaConfig, ColumnSpec


# ---------------------------------------------------------------------------
# 輔助工具
# ---------------------------------------------------------------------------

def _make_string_series(values: list) -> pd.Series:
    """建立 StringDtype Series，模擬 SourceReader 的全字串讀取輸出。"""
    return pd.Series(pd.array(values, dtype="string"), name="test_col")


def _infer(discovery: SchemaDiscovery, values: list) -> ColumnInferenceResult:
    """直接測試單欄推斷（繞過 SourceReader）。"""
    series = _make_string_series(values)
    return discovery._infer_column("test_col", series, required_threshold=0.05)


def _make_draft() -> SchemaDraft:
    """建立可重用的測試草稿物件。"""
    schema = SchemaConfig(columns=[
        ColumnSpec(source="交易日期", target="transaction_date", dtype="DATE", required=True),
        ColumnSpec(source="金額", target="amount", dtype="BIGINT", required=True),
        ColumnSpec(source="備註", target="remarks", dtype="VARCHAR", required=False),
    ])
    results = [
        ColumnInferenceResult(
            source="交易日期", suggested_dtype="DATE",
            null_rate=0.0, sample_values=["2024-01-01"],
            suggested_required=True, confidence=0.98,
        ),
        ColumnInferenceResult(
            source="金額", suggested_dtype="BIGINT",
            null_rate=0.02, sample_values=["1000", "2500"],
            suggested_required=True, confidence=0.95,
        ),
        ColumnInferenceResult(
            source="備註", suggested_dtype="VARCHAR",
            null_rate=0.30, sample_values=["轉帳", "匯款"],
            suggested_required=False, confidence=1.0,
        ),
    ]
    return SchemaDraft(
        schema_config=schema,
        inference_results=results,
        source_file="bank_statement.xlsx",
    )


# ---------------------------------------------------------------------------
# 型別推斷測試
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestSchemaDiscoveryTypInference:
    """各型別分支的推斷測試。"""

    def setup_method(self):
        self.discovery = SchemaDiscovery()

    def test_infer_boolean_english(self):
        """英文布林值（true/false）→ BOOLEAN。"""
        result = _infer(self.discovery, ["true", "false", "true", "false", "true"])
        assert result.suggested_dtype == "BOOLEAN"
        assert result.confidence == 1.0

    def test_infer_boolean_yes_no(self):
        """yes/no → BOOLEAN。"""
        result = _infer(self.discovery, ["yes", "no", "yes", "yes"])
        assert result.suggested_dtype == "BOOLEAN"

    def test_infer_boolean_chinese(self):
        """中文布林值（是/否）→ BOOLEAN。"""
        result = _infer(self.discovery, ["是", "否", "是", "是"])
        assert result.suggested_dtype == "BOOLEAN"

    def test_infer_bigint(self):
        """純整數字串 → BIGINT。"""
        result = _infer(self.discovery, ["100", "200", "300", "400"])
        assert result.suggested_dtype == "BIGINT"
        assert result.confidence >= 0.9

    def test_infer_double(self):
        """含小數的數值字串 → DOUBLE。"""
        result = _infer(self.discovery, ["1.5", "2.3", "100.0", "0.5"])
        assert result.suggested_dtype == "DOUBLE"
        assert result.confidence >= 0.9

    def test_infer_date(self):
        """純日期字串（無時間）→ DATE。"""
        result = _infer(self.discovery, ["2024-01-01", "2024-02-15", "2024-03-20"])
        assert result.suggested_dtype == "DATE"
        assert result.confidence >= 0.8

    def test_infer_datetime(self):
        """含時間的日期字串 → DATETIME。"""
        result = _infer(self.discovery, [
            "2024-01-01 10:30:00",
            "2024-02-15 14:20:30",
            "2024-03-20 08:00:00",
        ])
        assert result.suggested_dtype == "DATETIME"
        assert result.confidence >= 0.8

    def test_infer_varchar_fallback(self):
        """無法歸類的混合文字 → VARCHAR fallback。"""
        result = _infer(self.discovery, ["ABC-001", "XYZ-999", "混合text123"])
        assert result.suggested_dtype == "VARCHAR"


# ---------------------------------------------------------------------------
# 空值率與 required 測試
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestNullRateAndRequired:
    """空值率計算與 suggested_required 邊界測試。"""

    def setup_method(self):
        self.discovery = SchemaDiscovery()

    def test_infer_all_null_column(self):
        """全空欄位 → VARCHAR，null_rate=1.0，suggested_required=False。"""
        result = _infer(self.discovery, [None, None, None, None])
        assert result.suggested_dtype == "VARCHAR"
        assert result.null_rate == 1.0
        assert result.suggested_required is False
        assert result.sample_values == []

    def test_empty_string_counts_as_null(self):
        """空字串應算作 null（3 空字串 + 2 有值 → null_rate ≈ 0.6）。"""
        result = _infer(self.discovery, ["", "", "", "100", "200"])
        assert abs(result.null_rate - 0.6) < 0.01

    def test_required_threshold_below(self):
        """null_rate = 0.0 < 0.05 → suggested_required = True。"""
        result = _infer(self.discovery, ["100", "200", "300", "400", "500"])
        assert result.suggested_required is True

    def test_required_threshold_above(self):
        """null_rate = 0.6 >= 0.05 → suggested_required = False。"""
        result = _infer(self.discovery, [None, None, None, "100", "200"])
        assert result.suggested_required is False

    def test_sample_values_max_five(self):
        """樣本值最多 5 個。"""
        result = _infer(self.discovery, [str(i) for i in range(20)])
        assert len(result.sample_values) <= 5


# ---------------------------------------------------------------------------
# SchemaDraft 方法測試
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestSchemaDraft:
    """SchemaDraft 的三個方法測試。"""

    def test_to_schema_config(self):
        """to_schema_config() 回傳正確的 SchemaConfig。"""
        draft = _make_draft()
        config = draft.to_schema_config()

        assert isinstance(config, SchemaConfig)
        assert len(config.columns) == 3
        assert config.columns[0].dtype == "DATE"
        assert config.columns[1].dtype == "BIGINT"
        assert config.columns[2].dtype == "VARCHAR"

    def test_to_schema_config_returns_same_object(self):
        """to_schema_config() 回傳的是同一個 SchemaConfig 參照。"""
        draft = _make_draft()
        assert draft.to_schema_config() is draft.schema_config

    def test_summary_contains_column_names(self):
        """summary() 包含所有欄位名稱。"""
        draft = _make_draft()
        summary = draft.summary()
        assert "交易日期" in summary
        assert "金額" in summary
        assert "備註" in summary

    def test_summary_contains_dtypes(self):
        """summary() 包含推斷型別。"""
        summary = _make_draft().summary()
        assert "DATE" in summary
        assert "BIGINT" in summary
        assert "VARCHAR" in summary

    def test_summary_contains_confidence(self):
        """summary() 包含信心度百分比。"""
        summary = _make_draft().summary()
        assert "98%" in summary

    def test_summary_contains_source_file(self):
        """summary() 包含來源檔案名稱。"""
        summary = _make_draft().summary()
        assert "bank_statement.xlsx" in summary

    def test_to_yaml_valid_output(self, tmp_path):
        """to_yaml() 輸出可被 SchemaConfig.from_yaml() 讀回。"""
        draft = _make_draft()
        yaml_path = tmp_path / "test_schema.yaml"
        draft.to_yaml(yaml_path)

        assert yaml_path.exists()

        loaded = SchemaConfig.from_yaml(yaml_path)
        assert len(loaded.columns) == 3
        assert loaded.columns[0].source == "交易日期"
        assert loaded.columns[0].dtype == "DATE"
        assert loaded.columns[0].required is True
        assert loaded.columns[1].source == "金額"
        assert loaded.columns[1].dtype == "BIGINT"

    def test_to_yaml_creates_parent_dirs(self, tmp_path):
        """to_yaml() 自動建立不存在的父目錄。"""
        draft = _make_draft()
        yaml_path = tmp_path / "nested" / "deep" / "schema.yaml"
        draft.to_yaml(yaml_path)
        assert yaml_path.exists()

    def test_to_yaml_contains_draft_comment(self, tmp_path):
        """匯出的 YAML 包含草稿提示注釋。"""
        draft = _make_draft()
        yaml_path = tmp_path / "schema.yaml"
        draft.to_yaml(yaml_path)

        content = yaml_path.read_text(encoding="utf-8")
        assert "推斷草稿" in content
        assert "請人工確認" in content

    def test_to_yaml_missing_pyyaml(self, tmp_path):
        """pyyaml 未安裝時，to_yaml() 拋出帶有安裝提示的 ImportError。"""
        draft = _make_draft()
        # 模擬 yaml 模組不存在
        with patch.dict(sys.modules, {"yaml": None}):
            with pytest.raises(ImportError, match="PyYAML"):
                draft.to_yaml(tmp_path / "schema.yaml")


# ---------------------------------------------------------------------------
# _normalize_column_name 輔助函數測試
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestNormalizeColumnName:
    """_normalize_column_name() 邊界條件測試。"""

    def test_chinese_name(self):
        result = _normalize_column_name("交易日期")
        assert result.isidentifier()

    def test_space_replaced(self):
        result = _normalize_column_name("transaction date")
        assert " " not in result

    def test_leading_digit(self):
        result = _normalize_column_name("1st_column")
        assert not result[0].isdigit()

    def test_empty_string(self):
        assert _normalize_column_name("") == "col"

    def test_lowercase(self):
        result = _normalize_column_name("TransactionDate")
        assert result == result.lower()
