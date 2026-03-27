"""
Silver Layer 處理器

負責清洗轉換處理:
- 欄位映射
- 安全類型轉換
- 過濾無效行
- Circuit Breaker 檢查

Example:
    >>> processor = SilverProcessor()
    >>> df = processor.process(df_bronze, schema_config)
"""

import pandas as pd
import logging

from ..config import SchemaConfig, ColumnSpec
from ..transformers import ColumnMapper, SafeTypeCaster
from ..validation import CircuitBreaker


class SilverProcessor:
    """
    Silver Layer 處理器 - 清洗轉換

    組合 ColumnMapper、SafeTypeCaster、CircuitBreaker 執行完整的清洗流程。

    Attributes:
        column_mapper: 欄位映射器
        type_caster: 類型轉換器
        circuit_breaker: NULL 比例檢測器
        logger: 日誌器

    Example:
        >>> processor = SilverProcessor()
        >>> df_silver = processor.process(df_bronze, schema_config)
    """

    def __init__(
        self,
        column_mapper: ColumnMapper = None,
        type_caster: SafeTypeCaster = None,
        circuit_breaker: CircuitBreaker = None,
        logger: logging.Logger = None
    ):
        """
        初始化 SilverProcessor

        Args:
            column_mapper: 欄位映射器 (None 使用預設)
            type_caster: 類型轉換器 (None 使用預設)
            circuit_breaker: Circuit Breaker (None 使用預設)
            logger: 外部日誌器
        """
        self.logger = logger or logging.getLogger(__name__)
        self.column_mapper = column_mapper or ColumnMapper(self.logger)
        self.type_caster = type_caster or SafeTypeCaster(self.logger)
        self.circuit_breaker = circuit_breaker  # 可為 None

    def process(
        self,
        df: pd.DataFrame,
        schema_config: SchemaConfig,
        validate: bool = True
    ) -> pd.DataFrame:
        """
        處理 Silver 層邏輯

        處理步驟:
        1. 欄位映射
        2. 套用預設值
        3. 安全類型轉換
        4. 過濾空行
        5. Circuit Breaker 檢查

        Args:
            df: Bronze 層 DataFrame
            schema_config: Schema 配置
            validate: 是否執行 Circuit Breaker 檢查

        Returns:
            pd.DataFrame: 清洗後的 DataFrame

        Raises:
            SchemaValidationError: 必要欄位缺失
            CircuitBreakerError: NULL 比例超過閾值

        Example:
            >>> df_clean = processor.process(df_bronze, schema_config)
        """
        self.logger.info(f"開始 Silver 處理 ({len(df)} 行)")

        # 1. 欄位映射
        df = self.column_mapper.map_columns(
            df,
            schema_config.columns,
            preserve_unmapped=schema_config.preserve_unmapped
        )
        self.logger.debug(f"欄位映射完成: {list(df.columns)}")

        # 2. 套用預設值
        df = self.column_mapper.apply_defaults(df, schema_config.columns)

        # 3. 安全類型轉換
        df = self.type_caster.cast_columns(df, schema_config.columns)
        cast_summary = self.type_caster.get_cast_summary()
        if cast_summary["total_failures"] > 0:
            self.logger.info(f"類型轉換摘要: {cast_summary['failures_by_column']}")

        # 4. 過濾空行
        if schema_config.filter_empty_rows:
            original_len = len(df)
            df = self._filter_empty_rows(df, schema_config.columns)
            removed = original_len - len(df)
            if removed > 0:
                self.logger.info(f"過濾 {removed} 筆空行")

        # 5. Circuit Breaker 檢查
        if validate:
            breaker = self.circuit_breaker or CircuitBreaker(
                threshold=schema_config.circuit_breaker_threshold,
                logger=self.logger
            )
            breaker.check_and_raise(df, schema_config.columns)
            self.logger.debug("Circuit Breaker 檢查通過")

        self.logger.info(f"Silver 處理完成 ({len(df)} 行)")
        return df

    def _filter_empty_rows(
        self,
        df: pd.DataFrame,
        column_specs: list[ColumnSpec]
    ) -> pd.DataFrame:
        """
        過濾全空行

        判定標準: 所有目標欄位都是 NULL 或空字串
        """
        target_cols = [
            spec.target for spec in column_specs
            if spec.target in df.columns and not spec.target.startswith("_")
        ]

        if not target_cols:
            return df

        # 建立遮罩: 至少有一個非空值
        def is_empty(val):
            if pd.isna(val):
                return True
            if isinstance(val, str) and val.strip() == "":
                return True
            return False

        mask = df[target_cols].apply(
            lambda row: not all(is_empty(v) for v in row),
            axis=1
        )

        return df[mask].reset_index(drop=True)

    def validate_only(
        self,
        df: pd.DataFrame,
        schema_config: SchemaConfig
    ) -> dict:
        """
        僅執行驗證，不修改資料

        Args:
            df: DataFrame
            schema_config: Schema 配置

        Returns:
            dict: 驗證結果摘要
        """
        # 檢查欄位
        missing_required = self.column_mapper.validate_required_columns(
            df, schema_config.columns
        )

        # 先做映射、轉換，再執行 Circuit Breaker 檢查
        cb_result = None
        validation_error = None
        try:
            df_mapped = self.column_mapper.map_columns(
                df, schema_config.columns, preserve_unmapped=True
            )
            df_casted = self.type_caster.cast_columns(df_mapped, schema_config.columns)
            breaker = self.circuit_breaker or CircuitBreaker(
                threshold=schema_config.circuit_breaker_threshold
            )
            cb_result = breaker.check(df_casted, schema_config.columns)
        except Exception as e:
            # 保留錯誤訊息供呼叫者診斷；cb_result 保持 None 代表驗證無法完成
            validation_error = str(e)

        return {
            # cb_result is None 代表驗證過程失敗，不等同於「通過」
            "valid": (
                len(missing_required) == 0
                and validation_error is None
                and cb_result is not None
                and cb_result.is_ok
            ),
            "missing_required_columns": missing_required,
            "circuit_breaker_result": cb_result,
            "validation_error": validation_error,
        }
