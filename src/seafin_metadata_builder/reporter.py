"""
資料品質錯誤報告

提供行級別的轉換失敗詳情與 CircuitBreaker 結果，
可匯出為 Excel 供需求單位追查原始資料問題。

Example:
    >>> builder = MetadataBuilder()
    >>> df_silver, report = builder.build('./bank.xlsx', schema, return_report=True)
    >>> if report.has_errors:
    ...     report.to_excel('./data_quality_report.xlsx')
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:
    from .validation.circuit_breaker import CircuitBreakerResult


@dataclass
class CastFailureDetail:
    """
    單筆轉換失敗記錄

    Attributes:
        row_index: Silver 處理流程中（filter_empty_rows 前）的行號
        column: 發生失敗的 target 欄位名稱
        original_value: 型別轉換前的原始字串值
    """

    row_index: int
    column: str
    original_value: str


@dataclass
class ErrorReport:
    """
    資料品質錯誤報告

    收集 SafeTypeCaster 的行級別轉換失敗記錄與 CircuitBreaker 結果，
    可產出 Excel 報告交給需求單位追查原始資料問題。

    Attributes:
        cast_failures: 行級別轉換失敗清單（每筆含 row_index、欄位、原始值）
        cast_summary: 各欄位轉換失敗筆數摘要
        circuit_breaker_result: CircuitBreaker 結果；None 表示未執行或未觸發
        total_rows: Silver 處理完成後的資料總行數

    Example:
        >>> df_silver, report = builder.build('./bank.xlsx', schema, return_report=True)
        >>> print(report.summary())
        >>> if report.has_errors:
        ...     report.to_excel('./output/data_quality_report.xlsx')
    """

    cast_failures: list[CastFailureDetail] = field(default_factory=list)
    cast_summary: dict[str, int] = field(default_factory=dict)
    circuit_breaker_result: "CircuitBreakerResult | None" = None
    total_rows: int = 0

    @property
    def has_errors(self) -> bool:
        """
        是否有任何資料品質問題

        Returns:
            True 若有任何 cast 轉換失敗 或 CircuitBreaker 被觸發
        """
        if self.cast_failures:
            return True
        if self.circuit_breaker_result and self.circuit_breaker_result.is_tripped:
            return True
        return False

    def to_dataframe(self) -> pd.DataFrame:
        """
        回傳錯誤明細 DataFrame

        包含 row_index、column、original_value、issue_type 四欄。
        無任何錯誤時回傳含欄位標題的空 DataFrame。

        Returns:
            pd.DataFrame: 錯誤明細
        """
        rows = [
            {
                "row_index": f.row_index,
                "column": f.column,
                "original_value": f.original_value,
                "issue_type": "CAST_FAILURE",
            }
            for f in self.cast_failures
        ]

        if self.circuit_breaker_result and self.circuit_breaker_result.is_tripped:
            for col in self.circuit_breaker_result.tripped_columns:
                null_ratio = self.circuit_breaker_result.null_ratios.get(col, 0.0)
                rows.append(
                    {
                        "row_index": None,
                        "column": col,
                        "original_value": (
                            f"null_rate={null_ratio:.1%}，"
                            f"超過 threshold={self.circuit_breaker_result.threshold:.0%}"
                        ),
                        "issue_type": "CIRCUIT_BREAKER",
                    }
                )

        if not rows:
            return pd.DataFrame(
                columns=["row_index", "column", "original_value", "issue_type"]
            )
        return pd.DataFrame(rows)

    def to_excel(self, path: str | Path) -> None:
        """
        匯出錯誤報告 Excel

        產出含兩個 sheet 的 Excel 檔案：
        - **Summary**：各欄位失敗筆數與 CircuitBreaker 狀態摘要
        - **Detail**：每一筆失敗行的 row_index、欄位、原始值、問題類型

        Args:
            path: 輸出 Excel 路徑，父目錄不存在時自動建立
        """
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        # 建構 Summary sheet 資料
        summary_rows = []
        for col, count in self.cast_summary.items():
            summary_rows.append(
                {
                    "欄位": col,
                    "問題類型": "CAST_FAILURE",
                    "失敗筆數": count,
                    "備註": "",
                }
            )

        if self.circuit_breaker_result:
            for col in self.circuit_breaker_result.tripped_columns:
                null_ratio = self.circuit_breaker_result.null_ratios.get(col, 0.0)
                summary_rows.append(
                    {
                        "欄位": col,
                        "問題類型": "CIRCUIT_BREAKER",
                        "失敗筆數": 0,
                        "備註": (
                            f"null_rate={null_ratio:.1%}，"
                            f"threshold={self.circuit_breaker_result.threshold:.0%}"
                        ),
                    }
                )

        df_summary = pd.DataFrame(
            summary_rows if summary_rows else [],
            columns=["欄位", "問題類型", "失敗筆數", "備註"],
        )

        with pd.ExcelWriter(path, engine="openpyxl") as writer:
            df_summary.to_excel(writer, sheet_name="Summary", index=False)
            self.to_dataframe().to_excel(writer, sheet_name="Detail", index=False)

    def summary(self) -> str:
        """
        產生人可讀的錯誤摘要字串

        Returns:
            str: 格式化摘要，包含總行數、cast 失敗統計與 CircuitBreaker 狀態
        """
        total_cast_failures = sum(self.cast_summary.values())
        lines = [
            "資料品質報告摘要",
            "-" * 50,
            f"總行數: {self.total_rows}",
            f"轉換失敗總計: {total_cast_failures} 筆",
        ]

        if self.cast_summary:
            lines.append("  各欄位失敗筆數:")
            for col, count in self.cast_summary.items():
                lines.append(f"    {col}: {count} 筆")

        if self.circuit_breaker_result:
            status = self.circuit_breaker_result.status
            lines.append(f"CircuitBreaker 狀態: {status}")
            if self.circuit_breaker_result.is_tripped:
                for col in self.circuit_breaker_result.tripped_columns:
                    null_ratio = self.circuit_breaker_result.null_ratios.get(col, 0.0)
                    lines.append(
                        f"  觸發欄位: {col} "
                        f"(null_rate={null_ratio:.1%}, "
                        f"threshold={self.circuit_breaker_result.threshold:.0%})"
                    )
        else:
            lines.append("CircuitBreaker 狀態: 未執行")

        lines.append("-" * 50)
        return "\n".join(lines)
