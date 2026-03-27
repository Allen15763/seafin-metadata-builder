"""
欄位映射器

根據 ColumnSpec 配置將源欄位映射到目標欄位。

支援:
- 精確匹配
- Regex 匹配 (source 包含 '.*' 或 '|')

Example:
    >>> mapper = ColumnMapper()
    >>> df = mapper.map_columns(df, column_specs)
"""

import pandas as pd
import re
import logging
from typing import Any

from ..config import ColumnSpec
from ..exceptions import ColumnMappingError, SchemaValidationError


class ColumnMapper:
    """
    欄位映射器

    設計原則:
    - 支援精確匹配和 regex 匹配
    - 必要欄位缺失時報錯
    - 可選保留未映射欄位

    Attributes:
        logger: 日誌器

    Example:
        >>> mapper = ColumnMapper()
        >>> df = mapper.map_columns(df, [
        ...     ColumnSpec(source='交易日期', target='date'),
        ...     ColumnSpec(source='.*金額.*', target='amount'),
        ... ])
    """

    def __init__(self, logger: logging.Logger = None):
        """
        初始化 ColumnMapper

        Args:
            logger: 外部日誌器
        """
        self.logger = logger or logging.getLogger(__name__)

    def map_columns(
        self,
        df: pd.DataFrame,
        column_specs: list[ColumnSpec],
        preserve_unmapped: bool = False
    ) -> pd.DataFrame:
        """
        根據 ColumnSpec 映射欄位

        Args:
            df: 原始 DataFrame
            column_specs: 欄位定義列表
            preserve_unmapped: 是否保留未映射的欄位

        Returns:
            pd.DataFrame: 映射後的 DataFrame

        Raises:
            SchemaValidationError: 必要欄位缺失
            ColumnMappingError: 欄位映射失敗

        Example:
            >>> df_mapped = mapper.map_columns(df, specs)
        """
        df = df.copy()
        available_columns = list(df.columns)
        mapped_columns: dict[str, str] = {}  # target -> source
        missing_required: list[str] = []

        # 執行映射
        for spec in column_specs:
            source_col = self.find_matching_column(available_columns, spec.source)

            if source_col is None:
                if spec.required:
                    missing_required.append(spec.source)
                    self.logger.warning(f"缺少必要欄位: {spec.source}")
                else:
                    self.logger.debug(f"欄位 '{spec.source}' 未找到，跳過")
                continue

            mapped_columns[spec.target] = source_col
            self.logger.debug(f"映射: {source_col} -> {spec.target}")

        # 檢查必要欄位
        if missing_required:
            raise SchemaValidationError(missing_required)

        # 重新命名欄位
        rename_map = {v: k for k, v in mapped_columns.items()}
        df = df.rename(columns=rename_map)

        # 過濾欄位
        if not preserve_unmapped:
            target_cols = list(mapped_columns.keys())
            # 保留 metadata 欄位 (以 _ 開頭)
            metadata_cols = [c for c in df.columns if c.startswith("_")]
            keep_cols = target_cols + metadata_cols
            df = df[[c for c in keep_cols if c in df.columns]]

        return df

    def find_matching_column(
        self,
        columns: list[str],
        pattern: str
    ) -> str | None:
        """
        使用 regex 或精確匹配找到對應欄位

        Args:
            columns: 可用欄位列表
            pattern: 匹配模式 (精確字串或 regex)

        Returns:
            str | None: 匹配到的欄位名，或 None
        """
        # 先嘗試精確匹配
        if pattern in columns:
            return pattern

        # 嘗試不區分大小寫的精確匹配
        pattern_lower = pattern.lower()
        for col in columns:
            if col.lower() == pattern_lower:
                return col

        # 判斷是否為 regex pattern
        is_regex = (
            ".*" in pattern or
            "|" in pattern or
            pattern.startswith("^") or
            pattern.endswith("$")
        )

        if not is_regex:
            return None

        # Regex 匹配
        try:
            regex = re.compile(pattern, re.IGNORECASE)
            for col in columns:
                if regex.search(col):
                    return col
        except re.error as e:
            raise ColumnMappingError(
                source_pattern=pattern,
                available_columns=columns,
                reason=f"Regex 語法錯誤: {e}"
            ) from e

        return None

    def validate_required_columns(
        self,
        df: pd.DataFrame,
        column_specs: list[ColumnSpec]
    ) -> list[str]:
        """
        驗證 DataFrame 是否包含所有必要欄位

        Args:
            df: DataFrame
            column_specs: 欄位定義列表

        Returns:
            list[str]: 缺失的必要欄位列表
        """
        available = list(df.columns)
        missing = []

        for spec in column_specs:
            if spec.required:
                if self.find_matching_column(available, spec.source) is None:
                    missing.append(spec.source)

        return missing

    def apply_defaults(
        self,
        df: pd.DataFrame,
        column_specs: list[ColumnSpec]
    ) -> pd.DataFrame:
        """
        為缺失的欄位套用預設值

        Args:
            df: DataFrame
            column_specs: 欄位定義列表

        Returns:
            pd.DataFrame: 套用預設值後的 DataFrame
        """
        df = df.copy()

        for spec in column_specs:
            if spec.target not in df.columns and spec.default is not None:
                df[spec.target] = spec.default
                self.logger.debug(f"套用預設值: {spec.target} = {spec.default}")

        return df
