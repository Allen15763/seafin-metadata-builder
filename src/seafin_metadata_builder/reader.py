"""
Metadata Builder - 強健的源檔案讀取器

支援多種檔案格式，採用容錯策略讀取髒亂的源資料。

Example:
    >>> from seafin_metadata_builder import SourceReader, SourceSpec
    >>> 
    >>> reader = SourceReader()
    >>> df = reader.read('./input/bank.xlsx', SourceSpec(sheet_name='Sheet1'))
"""

import pandas as pd
from pathlib import Path
from typing import Any
import logging

from .config import SourceSpec
from .exceptions import SourceFileError, SheetNotFoundError


class SourceReader:
    """
    強健的源檔案讀取器

    設計原則:
    - 容錯優先: 盡可能讀取資料，而非報錯
    - 全字串讀取: dtype='string' 避免類型推斷失敗
    - 自動識別格式: 根據副檔名自動選擇讀取方法

    Attributes:
        logger: 日誌器

    Example:
        >>> reader = SourceReader()
        >>> df = reader.read('bank.xlsx', SourceSpec(header_row=2))
    """

    def __init__(self, logger: logging.Logger = None):
        """
        初始化 SourceReader

        Args:
            logger: 外部日誌器，None 時使用內建
        """
        self.logger = logger or logging.getLogger(__name__)

    def read(
        self,
        file_path: str | Path,
        spec: SourceSpec = None,
        **kwargs
    ) -> pd.DataFrame:
        """
        讀取源檔案，自動識別格式

        Args:
            file_path: 檔案路徑
            spec: 源檔案規格配置
            **kwargs: 額外參數傳遞給底層讀取方法

        Returns:
            pd.DataFrame: 讀取的資料 (全字串)

        Raises:
            SourceFileError: 檔案讀取失敗

        Example:
            >>> df = reader.read('bank.xlsx', SourceSpec(sheet_name=0))
        """
        file_path = Path(file_path)
        spec = spec or SourceSpec()

        if not file_path.exists():
            raise SourceFileError(str(file_path), f"檔案不存在: {file_path}")

        # 根據副檔名選擇讀取方法
        suffix = file_path.suffix.lower()
        file_type = self._detect_file_type(suffix, spec.file_type)

        self.logger.debug(f"讀取檔案: {file_path} (類型: {file_type})")

        match file_type:
            case "excel":
                return self.read_excel(file_path, spec, **kwargs)
            case "csv":
                return self.read_csv(file_path, spec, **kwargs)
            case "parquet":
                return self.read_parquet(file_path, spec, **kwargs)
            case "json":
                return self.read_json(file_path, spec, **kwargs)
            case _:
                raise SourceFileError(
                    str(file_path),
                    f"不支援的檔案類型: {suffix}"
                )

    def _detect_file_type(self, suffix: str, hint: str) -> str:
        """根據副檔名偵測檔案類型"""
        suffix_mapping = {
            ".xlsx": "excel",
            ".xls": "excel",
            ".xlsm": "excel",
            ".csv": "csv",
            ".parquet": "parquet",
            ".pq": "parquet",
            ".json": "json",
            ".txt": "csv",  # txt 預設視為 CSV
        }
        return suffix_mapping.get(suffix, hint)

    def read_excel(
        self,
        file_path: str | Path,
        spec: SourceSpec,
        **kwargs
    ) -> pd.DataFrame:
        """
        讀取 Excel 檔案

        Args:
            file_path: 檔案路徑
            spec: 源檔案規格配置
            **kwargs: 額外參數

        Returns:
            pd.DataFrame: 讀取的資料

        Raises:
            SheetNotFoundError: Sheet 不存在
            SourceFileError: 讀取失敗
        """
        file_path = Path(file_path)

        # 建構 read_excel 參數
        read_kwargs: dict[str, Any] = {
            "sheet_name": spec.sheet_name,
            "header": spec.header_row,
            "skiprows": spec.skip_rows if spec.skip_rows > 0 else None,
        }

        # 全字串讀取
        if spec.read_as_string:
            read_kwargs["dtype"] = 'string'

        # 合併額外參數
        read_kwargs.update(kwargs)

        try:
            df = pd.read_excel(file_path, **read_kwargs)
            self.logger.info(
                f"成功讀取 Excel: {file_path.name} "
                f"(Sheet: {spec.sheet_name}, {len(df)} 行, {len(df.columns)} 欄)"
            )
            return df

        except ValueError as e:
            # Sheet 不存在
            if "Worksheet" in str(e) or "sheet" in str(e).lower():
                raise SheetNotFoundError(str(file_path), str(spec.sheet_name))
            raise SourceFileError(str(file_path), str(e))

        except Exception as e:
            raise SourceFileError(str(file_path), str(e))

    def read_csv(
        self,
        file_path: str | Path,
        spec: SourceSpec,
        **kwargs
    ) -> pd.DataFrame:
        """
        讀取 CSV 檔案

        Args:
            file_path: 檔案路徑
            spec: 源檔案規格配置
            **kwargs: 額外參數

        Returns:
            pd.DataFrame: 讀取的資料
        """
        file_path = Path(file_path)

        read_kwargs: dict[str, Any] = {
            "encoding": spec.encoding,
            "sep": spec.delimiter,
            "header": spec.header_row,
            "skiprows": spec.skip_rows if spec.skip_rows > 0 else None,
            "on_bad_lines": "warn",  # 容錯模式
        }

        if spec.read_as_string:
            read_kwargs["dtype"] = 'string'

        read_kwargs.update(kwargs)

        try:
            # 嘗試不同編碼
            try:
                df = pd.read_csv(file_path, **read_kwargs)
            except UnicodeDecodeError:
                self.logger.warning(
                    f"UTF-8 解碼失敗，嘗試 cp950 編碼: {file_path.name}"
                )
                read_kwargs["encoding"] = "cp950"
                df = pd.read_csv(file_path, **read_kwargs)

            self.logger.info(
                f"成功讀取 CSV: {file_path.name} ({len(df)} 行, {len(df.columns)} 欄)"
            )
            return df

        except Exception as e:
            raise SourceFileError(str(file_path), str(e))

    def read_parquet(
        self,
        file_path: str | Path,
        spec: SourceSpec,
        **kwargs
    ) -> pd.DataFrame:
        """
        讀取 Parquet 檔案

        Args:
            file_path: 檔案路徑
            spec: 源檔案規格配置
            **kwargs: 額外參數

        Returns:
            pd.DataFrame: 讀取的資料
        """
        file_path = Path(file_path)

        try:
            df = pd.read_parquet(file_path, **kwargs)

            # Parquet 檔案通常已有正確類型，如需全字串則轉換
            if spec.read_as_string:
                df = df.astype('string')

            self.logger.info(
                f"成功讀取 Parquet: {file_path.name} ({len(df)} 行, {len(df.columns)} 欄)"
            )
            return df

        except Exception as e:
            raise SourceFileError(str(file_path), str(e))

    def read_json(
        self,
        file_path: str | Path,
        spec: SourceSpec,
        **kwargs
    ) -> pd.DataFrame:
        """
        讀取 JSON 檔案

        Args:
            file_path: 檔案路徑
            spec: 源檔案規格配置
            **kwargs: 額外參數

        Returns:
            pd.DataFrame: 讀取的資料
        """
        file_path = Path(file_path)

        read_kwargs: dict[str, Any] = {
            "encoding": spec.encoding,
        }

        if spec.read_as_string:
            read_kwargs["dtype"] = 'string'

        read_kwargs.update(kwargs)

        try:
            df = pd.read_json(file_path, **read_kwargs)
            self.logger.info(
                f"成功讀取 JSON: {file_path.name} ({len(df)} 行, {len(df.columns)} 欄)"
            )
            return df

        except Exception as e:
            raise SourceFileError(str(file_path), str(e))

    def get_excel_sheet_names(self, file_path: str | Path) -> list[str]:
        """
        取得 Excel 檔案的所有 Sheet 名稱

        Args:
            file_path: 檔案路徑

        Returns:
            list[str]: Sheet 名稱列表
        """
        file_path = Path(file_path)

        try:
            xlsx = pd.ExcelFile(file_path)
            return xlsx.sheet_names
        except Exception as e:
            raise SourceFileError(str(file_path), f"無法讀取 Sheet 列表: {e}")
