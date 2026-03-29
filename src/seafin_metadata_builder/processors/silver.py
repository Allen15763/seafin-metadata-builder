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
from ..reporter import CastFailureDetail, ErrorReport


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
        validate: bool = True,
        return_report: bool = False,
    ) -> "pd.DataFrame | tuple[pd.DataFrame, ErrorReport]":
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
            return_report: 為 True 時回傳 (df, ErrorReport) tuple；
                           CircuitBreaker 觸發時不拋出例外，改存入 report。
                           預設 False，行為與原先完全相同。

        Returns:
            pd.DataFrame（return_report=False）或
            tuple[pd.DataFrame, ErrorReport]（return_report=True）

        Raises:
            SchemaValidationError: 必要欄位缺失
            CircuitBreakerError: NULL 比例超過閾值（僅 return_report=False 時）

        Example:
            >>> df_clean = processor.process(df_bronze, schema_config)
            >>> df_clean, report = processor.process(df_bronze, schema_config, return_report=True)
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
        if return_report:
            # 保留 cast 前的字串值，用於事後比對哪些 row 轉換失敗
            df_pre_cast = df.copy()

        df = self.type_caster.cast_columns(df, schema_config.columns)
        cast_summary = self.type_caster.get_cast_summary()
        if cast_summary["total_failures"] > 0:
            self.logger.info(f"類型轉換摘要: {cast_summary['failures_by_column']}")

        # 若需要 report，收集行級別轉換失敗詳情
        cast_failure_details: list[CastFailureDetail] = []
        if return_report:
            cast_failure_details = self._collect_cast_failures(
                df_pre_cast, df, schema_config.columns
            )

        # 4. 過濾空行
        if schema_config.filter_empty_rows:
            original_len = len(df)
            df = self._filter_empty_rows(df, schema_config.columns)
            removed = original_len - len(df)
            if removed > 0:
                self.logger.info(f"過濾 {removed} 筆空行")

        # 5. Circuit Breaker 檢查
        cb_result = None
        if validate:
            breaker = self.circuit_breaker or CircuitBreaker(
                threshold=schema_config.circuit_breaker_threshold,
                logger=self.logger
            )
            if return_report:
                # report 模式：捕捉結果而不拋出例外
                cb_result = breaker.check(df, schema_config.columns)
                if cb_result.is_tripped:
                    self.logger.warning(
                        f"Circuit Breaker 觸發（已記錄至 ErrorReport）: "
                        f"{cb_result.tripped_columns}"
                    )
                else:
                    self.logger.debug("Circuit Breaker 檢查通過")
            else:
                breaker.check_and_raise(df, schema_config.columns)
                self.logger.debug("Circuit Breaker 檢查通過")

        self.logger.info(f"Silver 處理完成 ({len(df)} 行)")

        if return_report:
            report = ErrorReport(
                cast_failures=cast_failure_details,
                cast_summary=cast_summary["failures_by_column"],
                circuit_breaker_result=cb_result,
                total_rows=len(df),
            )
            return df, report

        return df

    def _collect_cast_failures(
        self,
        df_pre: pd.DataFrame,
        df_post: pd.DataFrame,
        column_specs: list[ColumnSpec],
    ) -> list[CastFailureDetail]:
        """
        比對 cast 前後的 DataFrame，收集轉換失敗的行級別詳情

        判斷條件：cast 前非空（有原始值），cast 後變為 NULL

        Args:
            df_pre: 型別轉換前的 DataFrame（apply_defaults 後）
            df_post: 型別轉換後的 DataFrame
            column_specs: 欄位定義列表

        Returns:
            list[CastFailureDetail]: 每筆失敗記錄含 row_index、欄位、原始字串值
        """
        failures: list[CastFailureDetail] = []

        for spec in column_specs:
            col = spec.target
            if col not in df_pre.columns or col not in df_post.columns:
                continue
            # dtype=VARCHAR → SafeTypeCaster 跳過，不會有新增失敗
            if spec.dtype.upper() in ("VARCHAR", "STRING", "TEXT"):
                continue

            # 找出 cast 前非空、cast 後為空的 row
            pre_not_null = df_pre[col].notna()
            post_is_null = df_post[col].isna()
            failing_idx = df_pre.index[pre_not_null & post_is_null]

            for idx in failing_idx:
                failures.append(
                    CastFailureDetail(
                        row_index=int(idx),
                        column=col,
                        original_value=str(df_pre.at[idx, col]),
                    )
                )

        return failures

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
