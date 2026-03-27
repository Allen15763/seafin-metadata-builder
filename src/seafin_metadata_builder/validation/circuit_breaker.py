"""
Circuit Breaker - NULL 比例檢測

當資料中 NULL 值比例超過閾值時觸發，防止低品質資料進入下游。

Example:
    >>> breaker = CircuitBreaker(threshold=0.3)
    >>> result = breaker.check(df, column_specs)
    >>> if result.is_tripped:
    ...     raise CircuitBreakerError(...)
"""

import pandas as pd
from dataclasses import dataclass, field
from typing import Literal
import logging

from ..config import ColumnSpec


@dataclass
class CircuitBreakerResult:
    """
    Circuit Breaker 檢查結果

    Attributes:
        status: 狀態 ('OK' 或 'TRIPPED')
        null_ratios: 各欄位的 NULL 比例
        tripped_columns: 觸發的欄位列表
        threshold: 使用的閾值
        message: 結果訊息
    """
    status: Literal["OK", "TRIPPED"]
    null_ratios: dict[str, float] = field(default_factory=dict)
    tripped_columns: list[str] = field(default_factory=list)
    threshold: float = 0.3
    message: str = ""

    @property
    def is_tripped(self) -> bool:
        """是否觸發"""
        return self.status == "TRIPPED"

    @property
    def is_ok(self) -> bool:
        """是否通過"""
        return self.status == "OK"


class CircuitBreaker:
    """
    Circuit Breaker - NULL 比例檢測

    當轉換後資料的 NULL 比例超過閾值時觸發，
    防止品質過差的資料進入後續處理。

    Attributes:
        threshold: NULL 比例閾值 (0~1)
        logger: 日誌器

    Example:
        >>> breaker = CircuitBreaker(threshold=0.3)
        >>> result = breaker.check(df, specs)
        >>> print(result.status)  # 'OK' or 'TRIPPED'
    """

    def __init__(
        self,
        threshold: float = 0.3,
        logger: logging.Logger = None
    ):
        """
        初始化 CircuitBreaker

        Args:
            threshold: NULL 比例閾值 (預設 0.3 = 30%)
            logger: 外部日誌器
        """
        if not 0 <= threshold <= 1:
            raise ValueError(f"threshold 必須在 0~1 之間，目前值: {threshold}")

        self.threshold = threshold
        self.logger = logger or logging.getLogger(__name__)

    def check(
        self,
        df: pd.DataFrame,
        column_specs: list[ColumnSpec] = None,
        columns: list[str] = None
    ) -> CircuitBreakerResult:
        """
        檢查 NULL 比例

        Args:
            df: DataFrame
            column_specs: 欄位定義列表 (優先使用)
            columns: 要檢查的欄位列表 (column_specs 為 None 時使用)

        Returns:
            CircuitBreakerResult: 檢查結果
        """
        # 決定要檢查的欄位
        if column_specs:
            check_columns = [
                spec.target for spec in column_specs
                if spec.target in df.columns
            ]
        elif columns:
            check_columns = [c for c in columns if c in df.columns]
        else:
            # 檢查所有非 metadata 欄位
            check_columns = [c for c in df.columns if not c.startswith("_")]

        if not check_columns:
            return CircuitBreakerResult(
                status="OK",
                threshold=self.threshold,
                message="無需檢查的欄位"
            )

        # 計算 NULL 比例
        total_rows = len(df)
        null_ratios: dict[str, float] = {}
        tripped_columns: list[str] = []

        for col in check_columns:
            null_count = df[col].isna().sum()
            ratio = null_count / total_rows if total_rows > 0 else 0
            null_ratios[col] = ratio

            if ratio > self.threshold:
                tripped_columns.append(col)
                self.logger.warning(
                    f"欄位 '{col}' NULL 比例 {ratio:.1%} 超過閾值 {self.threshold:.0%}"
                )

        # 建構結果
        if tripped_columns:
            details = ", ".join(
                f"{col}: {null_ratios[col]:.1%}"
                for col in tripped_columns
            )
            return CircuitBreakerResult(
                status="TRIPPED",
                null_ratios=null_ratios,
                tripped_columns=tripped_columns,
                threshold=self.threshold,
                message=f"以下欄位 NULL 比例超過 {self.threshold:.0%}: {details}"
            )
        else:
            return CircuitBreakerResult(
                status="OK",
                null_ratios=null_ratios,
                tripped_columns=[],
                threshold=self.threshold,
                message="所有欄位 NULL 比例符合標準"
            )

    def check_and_raise(
        self,
        df: pd.DataFrame,
        column_specs: list[ColumnSpec] = None,
        columns: list[str] = None
    ) -> CircuitBreakerResult:
        """
        檢查 NULL 比例，觸發時拋出異常

        Args:
            df: DataFrame
            column_specs: 欄位定義列表
            columns: 要檢查的欄位列表

        Returns:
            CircuitBreakerResult: 成功時返回結果

        Raises:
            CircuitBreakerError: NULL 比例超過閾值
        """
        from ..exceptions import CircuitBreakerError

        result = self.check(df, column_specs, columns)

        if result.is_tripped:
            raise CircuitBreakerError(
                tripped_columns=result.tripped_columns,
                null_ratios=result.null_ratios,
                threshold=self.threshold
            )

        return result

    def get_null_summary(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        取得所有欄位的 NULL 統計摘要

        Args:
            df: DataFrame

        Returns:
            pd.DataFrame: 包含 column, null_count, null_ratio, exceeds_threshold
        """
        total_rows = len(df)
        records = []

        for col in df.columns:
            null_count = df[col].isna().sum()
            ratio = null_count / total_rows if total_rows > 0 else 0
            records.append({
                "column": col,
                "null_count": null_count,
                "null_ratio": ratio,
                "exceeds_threshold": ratio > self.threshold
            })

        return pd.DataFrame(records)
