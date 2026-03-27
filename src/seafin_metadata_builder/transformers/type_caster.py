"""
安全類型轉換器

將字串資料安全轉換為目標類型，失敗時變為 NULL 而非報錯。

Example:
    >>> caster = SafeTypeCaster()
    >>> df = caster.cast_columns(df, column_specs)
"""

import pandas as pd
import numpy as np
import logging
import re
from typing import Any

from ..config import ColumnSpec


class SafeTypeCaster:
    """
    安全類型轉換器 - 失敗變 NULL

    設計原則:
    - 轉換失敗不報錯，變為 NULL
    - 支援常見類型轉換
    - 可追蹤轉換失敗的資料

    Attributes:
        logger: 日誌器
        cast_failures: 記錄各欄位轉換失敗筆數

    Example:
        >>> caster = SafeTypeCaster()
        >>> df = caster.cast_columns(df, specs)
        >>> print(caster.cast_failures)  # {'amount': 5}
    """

    def __init__(self, logger: logging.Logger = None):
        """
        初始化 SafeTypeCaster

        Args:
            logger: 外部日誌器
        """
        self.logger = logger or logging.getLogger(__name__)
        self.cast_failures: dict[str, int] = {}

    def cast_columns(
        self,
        df: pd.DataFrame,
        column_specs: list[ColumnSpec]
    ) -> pd.DataFrame:
        """
        對指定欄位執行安全類型轉換

        Args:
            df: DataFrame
            column_specs: 欄位定義列表

        Returns:
            pd.DataFrame: 轉換後的 DataFrame
        """
        df = df.copy()
        self.cast_failures.clear()

        for spec in column_specs:
            if spec.target not in df.columns:
                continue

            dtype = spec.dtype.upper()

            # 記錄轉換前的 NULL 數，用於計算因轉換引入的新 NULL（排除原本就是空值的資料）
            pre_null_count = df[spec.target].isna().sum()

            # 根據目標類型選擇轉換方法
            match dtype:
                case "VARCHAR" | "STRING" | "TEXT":
                    continue  # 保持字串

                case "BIGINT" | "INTEGER" | "INT" | "INT64":
                    df[spec.target] = self.cast_to_integer(df[spec.target])

                case "DOUBLE" | "FLOAT" | "DECIMAL" | "NUMERIC":
                    df[spec.target] = self.cast_to_numeric(df[spec.target])

                case "DATE":
                    df[spec.target] = self.cast_to_date(
                        df[spec.target],
                        spec.date_format
                    )

                case "DATETIME" | "TIMESTAMP":
                    df[spec.target] = self.cast_to_datetime(
                        df[spec.target],
                        spec.date_format
                    )

                case "BOOLEAN" | "BOOL":
                    df[spec.target] = self.cast_to_boolean(df[spec.target])

                case _:
                    self.logger.warning(f"未知類型 {dtype}，保持原樣")

            # 只記錄轉換新引入的 NULL，不含原本就是空值的資料
            new_failures = int(df[spec.target].isna().sum() - pre_null_count)
            if new_failures > 0:
                self.cast_failures[spec.target] = new_failures

        return df

    def cast_to_integer(self, series: pd.Series) -> pd.Series:
        """
        安全轉換為整數

        處理:
        - 移除千分位逗號
        - 移除貨幣符號
        - 處理空字串
        """
        # 清理字串
        cleaned = series.astype('string').str.strip()
        cleaned = cleaned.str.replace(",", "", regex=False)
        cleaned = cleaned.str.replace("$", "", regex=False)
        cleaned = cleaned.str.replace("NT$", "", regex=False)
        cleaned = cleaned.str.replace("元", "", regex=False)

        # 處理空值標記
        cleaned = cleaned.replace(["", "nan", "None", "N/A", "-"], np.nan)

        # 轉換
        return pd.to_numeric(cleaned, errors="coerce").astype("Int64")

    def cast_to_numeric(self, series: pd.Series) -> pd.Series:
        """
        安全轉換為浮點數

        處理:
        - 移除千分位逗號
        - 移除貨幣符號
        - 處理百分比
        """
        cleaned = series.astype('string').str.strip()
        cleaned = cleaned.str.replace(",", "", regex=False)
        cleaned = cleaned.str.replace("$", "", regex=False)
        cleaned = cleaned.str.replace("NT$", "", regex=False)

        # 處理百分比
        is_percent = cleaned.str.endswith("%")
        cleaned = cleaned.str.replace("%", "", regex=False)

        # 處理空值標記
        cleaned = cleaned.replace(["", "nan", "None", "N/A", "-"], np.nan)

        result = pd.to_numeric(cleaned, errors="coerce")

        # 百分比轉換
        result = result.where(~is_percent, result / 100)

        return result

    def cast_to_date(
        self,
        series: pd.Series,
        date_format: str = None
    ) -> pd.Series:
        """
        安全轉換為日期

        Args:
            series: 資料序列
            date_format: 日期格式 (如 '%Y/%m/%d')

        Returns:
            pd.Series: 日期序列 (datetime64[ns])
        """
        cleaned = series.astype('string').str.strip()
        cleaned = cleaned.replace(["", "nan", "None", "N/A", "-"], np.nan)

        if date_format:
            result = pd.to_datetime(cleaned, format=date_format, errors="coerce")
        else:
            # 嘗試自動解析
            result = pd.to_datetime(cleaned, errors="coerce", dayfirst=False)

        return result.dt.date

    def cast_to_datetime(
        self,
        series: pd.Series,
        date_format: str = None
    ) -> pd.Series:
        """
        安全轉換為日期時間

        Args:
            series: 資料序列
            date_format: 日期時間格式

        Returns:
            pd.Series: datetime 序列
        """
        cleaned = series.astype('string').str.strip()
        cleaned = cleaned.replace(["", "nan", "None", "N/A", "-"], np.nan)

        if date_format:
            return pd.to_datetime(cleaned, format=date_format, errors="coerce")
        else:
            return pd.to_datetime(cleaned, errors="coerce")

    def cast_to_boolean(self, series: pd.Series) -> pd.Series:
        """
        安全轉換為布林值

        True 值: 'true', 'yes', '1', 'y', 't', '是'
        False 值: 'false', 'no', '0', 'n', 'f', '否'
        """
        true_values = {"true", "yes", "1", "y", "t", "是", "有"}
        false_values = {"false", "no", "0", "n", "f", "否", "無"}

        cleaned = series.astype('string').str.strip().str.lower()

        def convert(val: str) -> bool | None:
            if val in true_values:
                return True
            elif val in false_values:
                return False
            else:
                return None

        return cleaned.apply(convert).astype("boolean")

    def get_cast_summary(self) -> dict[str, Any]:
        """
        取得轉換摘要

        Returns:
            dict: 包含失敗統計的摘要
        """
        return {
            "total_failures": sum(self.cast_failures.values()),
            "failures_by_column": self.cast_failures.copy(),
        }
