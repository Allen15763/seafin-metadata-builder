"""
Bronze Layer 處理器

負責原樣落地處理:
- 標準化欄位名稱
- 添加 metadata 欄位
- 無論資料多髒都保留

Example:
    >>> processor = BronzeProcessor()
    >>> df = processor.process(df_raw, source_file='bank.xlsx')
"""

import pandas as pd
from datetime import datetime
from uuid import uuid4
from pathlib import Path
import re


class BronzeProcessor:
    """
    Bronze Layer 處理器 - 原樣落地

    設計原則:
    - 保留所有原始資料
    - 標準化欄位名稱 (可選)
    - 添加追溯用 metadata

    Attributes:
        normalize_columns: 是否標準化欄位名稱
        add_row_num: 是否添加原始行號

    Example:
        >>> processor = BronzeProcessor()
        >>> df = processor.process(df_raw, source_file='bank.xlsx', sheet_name='Sheet1')
    """

    def __init__(
        self,
        normalize_columns: bool = True,
        add_row_num: bool = False
    ):
        """
        初始化 BronzeProcessor

        Args:
            normalize_columns: 是否標準化欄位名稱 (去除空白、特殊字元)
            add_row_num: 是否添加 _row_num 欄位
        """
        self.normalize_columns = normalize_columns
        self.add_row_num = add_row_num

    def process(
        self,
        df: pd.DataFrame,
        source_file: str | Path = None,
        sheet_name: str | int = None,
        batch_id: str = None,
        add_metadata: bool = True
    ) -> pd.DataFrame:
        """
        處理 Bronze 層邏輯

        Args:
            df: 原始 DataFrame
            source_file: 來源檔案路徑
            sheet_name: Sheet 名稱
            batch_id: 批次 ID (None 則自動生成)
            add_metadata: 是否添加 metadata 欄位

        Returns:
            pd.DataFrame: 處理後的 DataFrame

        Example:
            >>> df_bronze = processor.process(
            ...     df_raw,
            ...     source_file='./input/bank.xlsx',
            ...     sheet_name='B2B',
            ...     add_metadata=True
            ... )
        """
        # 複製避免修改原始資料
        df = df.copy()

        # 標準化欄位名稱
        if self.normalize_columns:
            df.columns = [self._normalize_column_name(col) for col in df.columns]

        # 添加原始行號
        if self.add_row_num:
            df.insert(0, "_row_num", range(1, len(df) + 1))

        # 添加 metadata 欄位
        if add_metadata:
            df = self._add_metadata(df, source_file, sheet_name, batch_id)

        return df

    def _normalize_column_name(self, name: str) -> str:
        """
        標準化欄位名稱

        處理規則:
        - 去除前後空白
        - 替換空白為底線
        - 移除特殊字元 (保留中文、英文、數字、底線)
        - 合併連續底線

        Args:
            name: 原始欄位名稱

        Returns:
            str: 標準化後的名稱
        """
        if not isinstance(name, str):
            name = str(name)

        # 去除前後空白
        name = name.strip()

        # 替換空白為底線
        name = re.sub(r"\s+", "_", name)

        # 移除特殊字元 (保留中文、英文、數字、底線)
        name = re.sub(r"[^\w\u4e00-\u9fff]", "", name)

        # 合併連續底線
        name = re.sub(r"_+", "_", name)

        # 去除首尾底線
        name = name.strip("_")

        return name if name else "unnamed"

    def _add_metadata(
        self,
        df: pd.DataFrame,
        source_file: str | Path,
        sheet_name: str | int,
        batch_id: str
    ) -> pd.DataFrame:
        """
        添加 metadata 欄位

        欄位說明:
        - _source_file: 來源檔案名稱
        - _sheet_name: Sheet 名稱
        - _batch_id: 批次 ID (UUID)
        - _ingested_at: 載入時間 (ISO 格式)
        """
        now = datetime.now()
        batch_id = batch_id or str(uuid4())[:8]

        source_name = Path(source_file).name if source_file else "unknown"
        sheet_str = str(sheet_name) if sheet_name is not None else ""

        df["_source_file"] = source_name
        df["_sheet_name"] = sheet_str
        df["_batch_id"] = batch_id
        df["_ingested_at"] = now.isoformat()

        return df

    def get_metadata_columns(self) -> list[str]:
        """取得 metadata 欄位列表"""
        cols = ["_source_file", "_sheet_name", "_batch_id", "_ingested_at"]
        if self.add_row_num:
            cols.insert(0, "_row_num")
        return cols
