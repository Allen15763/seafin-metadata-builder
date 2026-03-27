"""
Metadata Builder 配置模組

支援多種配置方式:
- SourceSpec: 源檔案規格配置
- ColumnSpec: 欄位定義
- SchemaConfig: Schema 配置

Example:
    >>> from seafin_metadata_builder import SourceSpec, SchemaConfig, ColumnSpec
    >>> 
    >>> # 定義欄位映射
    >>> schema = SchemaConfig(columns=[
    ...     ColumnSpec(source='交易日期', target='date', dtype='DATE', required=True),
    ...     ColumnSpec(source='金額', target='amount', dtype='BIGINT'),
    ...     ColumnSpec(source='.*備註.*', target='remarks', dtype='VARCHAR'),
    ... ])
"""

from dataclasses import dataclass, field
from typing import Any, Literal
from pathlib import Path


@dataclass
class SourceSpec:
    """
    源檔案規格配置

    Attributes:
        file_type: 檔案類型 (excel, csv, parquet, json)
        encoding: 編碼 (預設 utf-8)
        read_as_string: 是否全部讀為字串 (預設 True)
        sheet_name: Excel Sheet 名稱或索引 (預設 0)
        header_row: Header 所在行 (0-indexed)
        skip_rows: 跳過的行數
        delimiter: CSV 分隔符

    Example:
        >>> spec = SourceSpec(
        ...     file_type='excel',
        ...     sheet_name='Sheet1',
        ...     header_row=2,
        ...     read_as_string=True
        ... )
    """
    file_type: Literal["excel", "csv", "parquet", "json"] = "excel"
    encoding: str = "utf-8"
    read_as_string: bool = True

    # Excel 專用
    sheet_name: str | int = 0
    header_row: int = 0
    skip_rows: int = 0

    # CSV 專用
    delimiter: str = ","

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SourceSpec":
        """從字典建立配置"""
        valid_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered_data = {k: v for k, v in data.items() if k in valid_fields}
        return cls(**filtered_data)

    def to_dict(self) -> dict[str, Any]:
        """轉換為字典"""
        return {
            "file_type": self.file_type,
            "encoding": self.encoding,
            "read_as_string": self.read_as_string,
            "sheet_name": self.sheet_name,
            "header_row": self.header_row,
            "skip_rows": self.skip_rows,
            "delimiter": self.delimiter,
        }


@dataclass
class ColumnSpec:
    """
    欄位定義

    Attributes:
        source: 來源欄位名 (支援 regex，以 '.*' 開頭或包含 '|' 判定為 regex)
        target: 目標欄位名
        dtype: 目標類型 (VARCHAR, BIGINT, INTEGER, DOUBLE, DATE, BOOLEAN)
        required: 是否為必要欄位
        default: 預設值 (當欄位不存在或值為 NULL 時)
        date_format: 日期格式 (僅 DATE 類型使用)

    Example:
        >>> col = ColumnSpec(
        ...     source='交易日期',
        ...     target='transaction_date',
        ...     dtype='DATE',
        ...     required=True,
        ...     date_format='%Y/%m/%d'
        ... )
    """
    source: str
    target: str
    dtype: str = "VARCHAR"
    required: bool = False
    default: Any = None
    date_format: str | None = None

    def __post_init__(self):
        """驗證 dtype"""
        valid_types = {
            "VARCHAR", "BIGINT", "INTEGER", "DOUBLE", "FLOAT",
            "DATE", "DATETIME", "TIMESTAMP", "BOOLEAN", "BOOL"
        }
        if self.dtype.upper() not in valid_types:
            raise ValueError(
                f"無效的 dtype: {self.dtype}，有效值: {valid_types}"
            )
        self.dtype = self.dtype.upper()

    @property
    def is_regex(self) -> bool:
        """判斷 source 是否為 regex pattern"""
        return (
            ".*" in self.source or
            "|" in self.source or
            self.source.startswith("^") or
            self.source.endswith("$")
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ColumnSpec":
        """從字典建立配置"""
        valid_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered_data = {k: v for k, v in data.items() if k in valid_fields}
        return cls(**filtered_data)


@dataclass
class SchemaConfig:
    """
    Schema 配置

    Attributes:
        columns: 欄位定義列表
        circuit_breaker_threshold: NULL 比例容忍度 (預設 0.3 = 30%)
        filter_empty_rows: 是否過濾全空行
        preserve_unmapped: 是否保留未映射的欄位

    Example:
        >>> schema = SchemaConfig(
        ...     columns=[
        ...         ColumnSpec(source='日期', target='date', dtype='DATE'),
        ...         ColumnSpec(source='金額', target='amount', dtype='BIGINT'),
        ...     ],
        ...     circuit_breaker_threshold=0.3
        ... )
    """
    columns: list[ColumnSpec] = field(default_factory=list)
    circuit_breaker_threshold: float = 0.3
    filter_empty_rows: bool = True
    preserve_unmapped: bool = False

    def __post_init__(self):
        """驗證配置"""
        if not 0 <= self.circuit_breaker_threshold <= 1:
            raise ValueError(
                f"circuit_breaker_threshold 必須在 0~1 之間，"
                f"目前值: {self.circuit_breaker_threshold}"
            )

    @property
    def required_columns(self) -> list[ColumnSpec]:
        """取得必要欄位"""
        return [col for col in self.columns if col.required]

    @property
    def target_columns(self) -> list[str]:
        """取得所有目標欄位名"""
        return [col.target for col in self.columns]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SchemaConfig":
        """
        從字典建立配置

        Args:
            data: 配置字典，格式如下:
                {
                    "columns": [
                        {"source": "日期", "target": "date", "dtype": "DATE"},
                        {"source": "金額", "target": "amount", "dtype": "BIGINT"},
                    ],
                    "circuit_breaker_threshold": 0.3,
                    "filter_empty_rows": True
                }
        """
        columns = [
            ColumnSpec.from_dict(col) if isinstance(col, dict) else col
            for col in data.get("columns", [])
        ]
        return cls(
            columns=columns,
            circuit_breaker_threshold=data.get("circuit_breaker_threshold", 0.3),
            filter_empty_rows=data.get("filter_empty_rows", True),
            preserve_unmapped=data.get("preserve_unmapped", False),
        )

    @classmethod
    def from_yaml(
        cls,
        path: str | Path,
        section: str = None
    ) -> "SchemaConfig":
        """
        從 YAML 檔案建立配置

        Args:
            path: YAML 檔案路徑
            section: 配置區段名稱 (如 'banks.cub')

        Raises:
            FileNotFoundError: 檔案不存在
            ImportError: 未安裝 PyYAML

        Example:
            >>> schema = SchemaConfig.from_yaml('schema.yaml', section='banks.cub')
        """
        try:
            import yaml
        except ImportError:
            raise ImportError(
                "需要安裝 PyYAML 套件才能讀取 YAML 配置。"
                "請執行: pip install pyyaml"
            )

        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"配置檔案不存在: {path}")

        with open(path, "r", encoding="utf-8") as f:
            yaml_data = yaml.safe_load(f)

        if yaml_data is None:
            raise ValueError(f"YAML 檔案為空或格式錯誤: {path}")

        # 支援嵌套 section (e.g., 'banks.cub')
        if section:
            for key in section.split("."):
                if key not in yaml_data:
                    raise KeyError(f"配置檔案中找不到 '{key}' 區段")
                yaml_data = yaml_data[key]

        return cls.from_dict(yaml_data)

    @classmethod
    def from_toml(
        cls,
        path: str | Path,
        section: str = None
    ) -> "SchemaConfig":
        """
        從 TOML 檔案建立配置

        Args:
            path: TOML 檔案路徑
            section: 配置區段名稱

        Raises:
            FileNotFoundError: 檔案不存在

        Example:
            >>> schema = SchemaConfig.from_toml('schema.toml', section='banks.cub')
        """
        import tomllib

        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"配置檔案不存在: {path}")

        with open(path, "rb") as f:
            toml_data = tomllib.load(f)

        # 支援嵌套 section
        if section:
            for key in section.split("."):
                if key not in toml_data:
                    raise KeyError(f"配置檔案中找不到 [{key}] 區段")
                toml_data = toml_data[key]

        return cls.from_dict(toml_data)

    def to_dict(self) -> dict[str, Any]:
        """轉換為字典"""
        return {
            "columns": [
                {
                    "source": col.source,
                    "target": col.target,
                    "dtype": col.dtype,
                    "required": col.required,
                    "default": col.default,
                    "date_format": col.date_format,
                }
                for col in self.columns
            ],
            "circuit_breaker_threshold": self.circuit_breaker_threshold,
            "filter_empty_rows": self.filter_empty_rows,
            "preserve_unmapped": self.preserve_unmapped,
        }
