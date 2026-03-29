"""
Metadata Builder Plugin

髒資料處理工具類，用於處理高度不可控的源資料（特別是 Excel）。
採用 Bronze/Silver 三層架構，作為 Pipeline Step 中可呼叫的工具。

主要類:
- MetadataBuilder: 核心工具類，提供 extract/transform/build API
- SourceSpec: 源檔案規格配置
- SchemaConfig: Schema 配置
- ColumnSpec: 欄位定義

Example:
    >>> from seafin_metadata_builder import MetadataBuilder, SchemaConfig, ColumnSpec
    >>> 
    >>> # 定義 Schema
    >>> schema = SchemaConfig(columns=[
    ...     ColumnSpec(source='交易日期', target='date', dtype='DATE', required=True),
    ...     ColumnSpec(source='金額', target='amount', dtype='BIGINT'),
    ... ])
    >>> 
    >>> # 使用 MetadataBuilder
    >>> builder = MetadataBuilder()
    >>> df = builder.build('./input/bank.xlsx', schema, sheet_name=0, header_row=2)
    >>> 
    >>> # 配合 DuckDBManager 使用
    >>> from seafin_duckdb_manager import DuckDBManager
    >>> with DuckDBManager('./db/data.duckdb') as db:
    ...     db.create_table_from_df('bank_statement', df, if_exists='replace')
"""

from .config import SourceSpec, SchemaConfig, ColumnSpec
from .builder import MetadataBuilder
from .reader import SourceReader
from .discovery import SchemaDiscovery, SchemaDraft, ColumnInferenceResult
from .reporter import ErrorReport, CastFailureDetail
from .processors import BronzeProcessor, SilverProcessor
from .transformers import ColumnMapper, SafeTypeCaster
from .validation import CircuitBreaker, CircuitBreakerResult
from .exceptions import (
    MetadataBuilderError,
    SourceFileError,
    SheetNotFoundError,
    SchemaValidationError,
    CircuitBreakerError,
    TypeCastingError,
    ColumnMappingError,
)

__all__ = [
    # 核心類
    "MetadataBuilder",
    "SourceSpec",
    "SchemaConfig",
    "ColumnSpec",
    # Schema 探索工具
    "SchemaDiscovery",
    "SchemaDraft",
    "ColumnInferenceResult",
    # 錯誤報告
    "ErrorReport",
    "CastFailureDetail",
    # 子組件
    "SourceReader",
    "BronzeProcessor",
    "SilverProcessor",
    "ColumnMapper",
    "SafeTypeCaster",
    "CircuitBreaker",
    "CircuitBreakerResult",
    # 異常
    "MetadataBuilderError",
    "SourceFileError",
    "SheetNotFoundError",
    "SchemaValidationError",
    "CircuitBreakerError",
    "TypeCastingError",
    "ColumnMappingError",
]

__version__ = "1.0.0"
