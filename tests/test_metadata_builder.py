"""MetadataBuilder 配置與核心類別單元測試"""
import pytest
from pathlib import Path

from seafin_metadata_builder.config import (
    SourceSpec, ColumnSpec, SchemaConfig,
)


@pytest.mark.unit
class TestSourceSpec:
    """SourceSpec 測試"""

    def test_defaults(self):
        spec = SourceSpec()
        assert spec.file_type == "excel"
        assert spec.encoding == "utf-8"
        assert spec.read_as_string is True
        assert spec.sheet_name == 0
        assert spec.header_row == 0
        assert spec.delimiter == ","

    def test_custom_values(self):
        spec = SourceSpec(
            file_type="csv", encoding="big5",
            delimiter="\t", header_row=2,
        )
        assert spec.file_type == "csv"
        assert spec.encoding == "big5"
        assert spec.delimiter == "\t"
        assert spec.header_row == 2

    def test_from_dict(self):
        spec = SourceSpec.from_dict({
            "file_type": "parquet",
            "unknown_field": "ignored",
        })
        assert spec.file_type == "parquet"

    def test_to_dict(self):
        spec = SourceSpec()
        d = spec.to_dict()
        assert "file_type" in d
        assert "encoding" in d
        assert "delimiter" in d


@pytest.mark.unit
class TestColumnSpec:
    """ColumnSpec 測試"""

    def test_basic_creation(self):
        col = ColumnSpec(source="金額", target="amount", dtype="BIGINT")
        assert col.source == "金額"
        assert col.target == "amount"
        assert col.dtype == "BIGINT"
        assert col.required is False
        assert col.default is None

    def test_invalid_dtype_raises(self):
        with pytest.raises(ValueError, match="無效的 dtype"):
            ColumnSpec(source="a", target="b", dtype="INVALID_TYPE")

    def test_dtype_normalized_to_upper(self):
        col = ColumnSpec(source="a", target="b", dtype="varchar")
        assert col.dtype == "VARCHAR"

    def test_is_regex_with_wildcard(self):
        col = ColumnSpec(source=".*備註.*", target="remarks")
        assert col.is_regex is True

    def test_is_regex_with_pipe(self):
        col = ColumnSpec(source="col_a|col_b", target="merged")
        assert col.is_regex is True

    def test_is_regex_with_anchor(self):
        col = ColumnSpec(source="^date$", target="date")
        assert col.is_regex is True

    def test_is_not_regex_plain_name(self):
        col = ColumnSpec(source="simple_name", target="name")
        assert col.is_regex is False

    def test_from_dict(self):
        col = ColumnSpec.from_dict({
            "source": "日期",
            "target": "date",
            "dtype": "DATE",
            "required": True,
            "date_format": "%Y/%m/%d",
        })
        assert col.required is True
        assert col.date_format == "%Y/%m/%d"

    def test_date_types_accepted(self):
        for dtype in ["DATE", "DATETIME", "TIMESTAMP"]:
            col = ColumnSpec(source="a", target="b", dtype=dtype)
            assert col.dtype == dtype

    def test_numeric_types_accepted(self):
        for dtype in ["BIGINT", "INTEGER", "DOUBLE", "FLOAT"]:
            col = ColumnSpec(source="a", target="b", dtype=dtype)
            assert col.dtype == dtype


@pytest.mark.unit
class TestSchemaConfig:
    """SchemaConfig 測試"""

    def test_defaults(self):
        schema = SchemaConfig()
        assert schema.columns == []
        assert schema.circuit_breaker_threshold == 0.3
        assert schema.filter_empty_rows is True
        assert schema.preserve_unmapped is False

    def test_invalid_threshold_raises(self):
        with pytest.raises(ValueError, match="circuit_breaker_threshold"):
            SchemaConfig(circuit_breaker_threshold=1.5)

    def test_negative_threshold_raises(self):
        with pytest.raises(ValueError):
            SchemaConfig(circuit_breaker_threshold=-0.1)

    def test_required_columns_property(self):
        schema = SchemaConfig(columns=[
            ColumnSpec(source="a", target="a", required=True),
            ColumnSpec(source="b", target="b", required=False),
            ColumnSpec(source="c", target="c", required=True),
        ])
        assert len(schema.required_columns) == 2

    def test_target_columns_property(self):
        schema = SchemaConfig(columns=[
            ColumnSpec(source="a", target="col_a"),
            ColumnSpec(source="b", target="col_b"),
        ])
        assert schema.target_columns == ["col_a", "col_b"]

    def test_from_dict(self):
        schema = SchemaConfig.from_dict({
            "columns": [
                {"source": "日期", "target": "date", "dtype": "DATE"},
                {"source": "金額", "target": "amount", "dtype": "BIGINT"},
            ],
            "circuit_breaker_threshold": 0.5,
        })
        assert len(schema.columns) == 2
        assert schema.circuit_breaker_threshold == 0.5

    def test_from_dict_with_column_spec_objects(self):
        col = ColumnSpec(source="a", target="b")
        schema = SchemaConfig.from_dict({"columns": [col]})
        assert len(schema.columns) == 1
        assert schema.columns[0] is col

    def test_to_dict(self):
        schema = SchemaConfig(columns=[
            ColumnSpec(source="a", target="b", dtype="VARCHAR"),
        ])
        d = schema.to_dict()
        assert len(d["columns"]) == 1
        assert d["columns"][0]["source"] == "a"
        assert "circuit_breaker_threshold" in d

    def test_from_toml(self, tmp_path):
        toml_content = """
[schema]
circuit_breaker_threshold = 0.2
filter_empty_rows = false

[[schema.columns]]
source = "col_date"
target = "date"
dtype = "DATE"
required = true
"""
        toml_file = tmp_path / "schema.toml"
        toml_file.write_bytes(toml_content.encode("utf-8"))
        schema = SchemaConfig.from_toml(str(toml_file), section="schema")
        assert schema.circuit_breaker_threshold == 0.2
        assert len(schema.columns) == 1
        assert schema.columns[0].required is True

    def test_from_toml_missing_file(self):
        with pytest.raises(FileNotFoundError):
            SchemaConfig.from_toml("/nonexistent/schema.toml")

    def test_boundary_threshold_zero(self):
        schema = SchemaConfig(circuit_breaker_threshold=0.0)
        assert schema.circuit_breaker_threshold == 0.0

    def test_boundary_threshold_one(self):
        schema = SchemaConfig(circuit_breaker_threshold=1.0)
        assert schema.circuit_breaker_threshold == 1.0
