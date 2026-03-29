"""
MetadataBuilder - 核心工具類

髒資料處理工具類，可在 Pipeline Step 中呼叫。

職責:
1. Bronze: 強健地讀取源檔案並標準化
2. Silver: 欄位映射、類型轉換、驗證
3. 返回處理後的 DataFrame，由呼叫者決定如何存入 DB

Example:
    >>> from seafin_metadata_builder import MetadataBuilder, SchemaConfig
    >>> 
    >>> builder = MetadataBuilder()
    >>> df = builder.build('./input/bank.xlsx', schema_config)
"""

import pandas as pd
from pathlib import Path
import logging
from typing import TYPE_CHECKING

from .config import SourceSpec, SchemaConfig
from .reader import SourceReader
from .processors import BronzeProcessor, SilverProcessor

if TYPE_CHECKING:
    from .reporter import ErrorReport


class MetadataBuilder:
    """
    髒資料處理工具類 - 可在 Pipeline Step 中呼叫

    設計原則:
    - 作為工具類被 Pipeline Step 呼叫，不綁定執行流程
    - 只負責資料處理，存入 DB 由呼叫者控制
    - 分離 Bronze 和 Silver 層操作，可單獨或組合使用

    Attributes:
        source_spec: 預設的源檔案規格
        reader: SourceReader 實例
        bronze_processor: BronzeProcessor 實例
        silver_processor: SilverProcessor 實例
        logger: 日誌器

    Example:
        >>> builder = MetadataBuilder()
        >>> 
        >>> # 分開呼叫
        >>> df_raw = builder.extract('./bank.xlsx', add_metadata=True)
        >>> df_clean = builder.transform(df_raw, schema_config)
        >>> 
        >>> # 或使用便利方法
        >>> df = builder.build('./bank.xlsx', schema_config)
    """

    def __init__(
        self,
        source_spec: SourceSpec = None,
        logger: logging.Logger = None
    ):
        """
        初始化 MetadataBuilder

        Args:
            source_spec: 預設的源檔案規格
            logger: 外部日誌器
        """
        self.source_spec = source_spec or SourceSpec()
        self.logger = logger or logging.getLogger(__name__)

        # 初始化子組件
        self.reader = SourceReader(self.logger)
        self.bronze_processor = BronzeProcessor()
        self.silver_processor = SilverProcessor(logger=self.logger)

    # ========== Bronze 層操作 ==========

    def extract(
        self,
        file_path: str | Path,
        sheet_name: str | int = None,
        header_row: int = None,
        add_metadata: bool = True,
        batch_id: str = None,
        **read_kwargs
    ) -> pd.DataFrame:
        """
        Bronze: 強健地讀取源檔案

        - 全部讀為 string (dtype='string')
        - 標準化欄位名稱
        - 可選添加 metadata 欄位

        Args:
            file_path: 檔案路徑
            sheet_name: Sheet 名稱 (覆蓋 source_spec)
            header_row: Header 行 (覆蓋 source_spec)
            add_metadata: 是否添加 metadata 欄位
            batch_id: 批次 ID (None 則自動生成)
            **read_kwargs: 額外參數傳遞給檔案讀取

        Returns:
            pd.DataFrame: 原始資料 (全字串)

        Raises:
            SourceFileError: 檔案讀取失敗

        Example:
            >>> df_raw = builder.extract(
            ...     './bank.xlsx',
            ...     sheet_name='B2B',
            ...     header_row=2
            ... )
        """
        file_path = Path(file_path)

        # 建構 SourceSpec
        spec = SourceSpec(
            file_type=self.source_spec.file_type,
            encoding=self.source_spec.encoding,
            read_as_string=True,  # 始終全字串讀取
            sheet_name=sheet_name if sheet_name is not None else self.source_spec.sheet_name,
            header_row=header_row if header_row is not None else self.source_spec.header_row,
            skip_rows=self.source_spec.skip_rows,
            delimiter=self.source_spec.delimiter,
        )

        self.logger.info(f"Bronze: 讀取檔案 {file_path.name}")

        # 讀取檔案
        df = self.reader.read(file_path, spec, **read_kwargs)

        # Bronze 處理
        df = self.bronze_processor.process(
            df,
            source_file=str(file_path),
            sheet_name=spec.sheet_name,
            batch_id=batch_id,
            add_metadata=add_metadata
        )

        self.logger.info(f"Bronze 完成: {len(df)} 行, {len(df.columns)} 欄")
        return df

    # ========== Silver 層操作 ==========

    def transform(
        self,
        df: pd.DataFrame,
        schema_config: SchemaConfig,
        validate: bool = True,
        return_report: bool = False,
    ) -> "pd.DataFrame | tuple[pd.DataFrame, ErrorReport]":
        """
        Silver: 清洗並轉換資料

        - 欄位映射（支援 regex）
        - 安全類型轉換（失敗變 NULL）
        - 過濾無效行
        - Circuit Breaker 檢查

        Args:
            df: Bronze 層 DataFrame
            schema_config: Schema 配置
            validate: 是否執行 Circuit Breaker 驗證
            return_report: 為 True 時回傳 (df, ErrorReport) tuple，
                           CircuitBreaker 觸發時不拋出例外改存入 report

        Returns:
            pd.DataFrame（return_report=False）或
            tuple[pd.DataFrame, ErrorReport]（return_report=True）

        Raises:
            CircuitBreakerError: NULL 比例超過閾值（僅 return_report=False 時）
            SchemaValidationError: 必要欄位缺失

        Example:
            >>> df_clean = builder.transform(df_raw, schema_config)
            >>> df_clean, report = builder.transform(df_raw, schema_config, return_report=True)
        """
        self.logger.info(f"Silver: 開始轉換 ({len(df)} 行)")

        result = self.silver_processor.process(
            df,
            schema_config,
            validate=validate,
            return_report=return_report,
        )

        if return_report:
            df_clean, report = result
            self.logger.info(f"Silver 完成: {len(df_clean)} 行")
            return df_clean, report

        self.logger.info(f"Silver 完成: {len(result)} 行")
        return result

    # ========== 便利方法 ==========

    def build(
        self,
        file_path: str | Path,
        schema_config: SchemaConfig,
        sheet_name: str | int = None,
        header_row: int = None,
        add_metadata: bool = True,
        validate: bool = True,
        return_report: bool = False,
        **extract_kwargs
    ) -> "pd.DataFrame | tuple[pd.DataFrame, ErrorReport]":
        """
        一次完成 Bronze + Silver

        Args:
            file_path: 檔案路徑
            schema_config: Schema 配置
            sheet_name: Sheet 名稱
            header_row: Header 行
            add_metadata: 是否添加 metadata 欄位
            validate: 是否執行驗證
            return_report: 為 True 時回傳 (df, ErrorReport) tuple，
                           CircuitBreaker 觸發時不拋出例外改存入 report
            **extract_kwargs: 額外參數傳遞給 extract

        Returns:
            pd.DataFrame（return_report=False）或
            tuple[pd.DataFrame, ErrorReport]（return_report=True）

        Example:
            >>> df = builder.build('./bank.xlsx', schema_config)
            >>> df, report = builder.build('./bank.xlsx', schema_config, return_report=True)
            >>> if report.has_errors:
            ...     report.to_excel('./data_quality_report.xlsx')
        """
        # Bronze
        df = self.extract(
            file_path,
            sheet_name=sheet_name,
            header_row=header_row,
            add_metadata=add_metadata,
            **extract_kwargs
        )

        # Silver
        return self.transform(df, schema_config, validate=validate, return_report=return_report)

    def extract_and_preview(
        self,
        file_path: str | Path,
        sheet_name: str | int = None,
        header_row: int = None,
        n_rows: int = 10
    ) -> dict:
        """
        讀取檔案並預覽，用於了解資料結構

        Args:
            file_path: 檔案路徑
            sheet_name: Sheet 名稱
            header_row: Header 行
            n_rows: 預覽行數

        Returns:
            dict: 包含 columns, dtypes, preview, shape

        Example:
            >>> info = builder.extract_and_preview('./bank.xlsx')
            >>> print(info['columns'])
        """
        df = self.extract(
            file_path,
            sheet_name=sheet_name,
            header_row=header_row,
            add_metadata=False
        )

        return {
            "columns": list(df.columns),
            "dtypes": df.dtypes.to_dict(),
            "preview": df.head(n_rows),
            "shape": df.shape,
        }

    def get_excel_sheets(self, file_path: str | Path) -> list[str]:
        """
        取得 Excel 檔案的 Sheet 列表

        Args:
            file_path: 檔案路徑

        Returns:
            list[str]: Sheet 名稱列表
        """
        return self.reader.get_excel_sheet_names(file_path)
