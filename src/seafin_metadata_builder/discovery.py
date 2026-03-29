"""
Schema 自動探索工具

從源檔案自動推斷 SchemaConfig 草稿，減少手動逆向工程 Excel 欄位的時間。

推斷流程：
1. 使用 SourceReader 讀取源檔案（全字串模式）
2. 針對每欄分析空值率、樣本值，並依優先順序推斷型別
3. 組裝 SchemaDraft，可匯出為 YAML 草稿供人工確認

Example:
    >>> from seafin_metadata_builder import SchemaDiscovery
    >>>
    >>> discovery = SchemaDiscovery()
    >>> draft = discovery.infer('./bank_statement.xlsx', sheet_name=0, header_row=2)
    >>> print(draft.summary())
    >>> draft.to_yaml('./config/schemas/bank_recon/bank_a_draft.yaml')
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from .config import ColumnSpec, SchemaConfig, SourceSpec
from .reader import SourceReader


@dataclass
class ColumnInferenceResult:
    """
    單欄型別推斷結果

    Attributes:
        source: 原始欄位名稱
        suggested_dtype: 推斷的目標型別
        null_rate: 空值比例（空字串也算空值，範圍 0.0 ~ 1.0）
        sample_values: 最多 5 個非空樣本值
        suggested_required: 是否建議設為必填欄位（由 null_rate < required_threshold 決定）
        confidence: 推斷信心度，等於成功轉換比例（0.0 ~ 1.0）
    """

    source: str
    suggested_dtype: str
    null_rate: float
    sample_values: list[Any]
    suggested_required: bool
    confidence: float


@dataclass
class SchemaDraft:
    """
    Schema 推斷草稿容器

    包含自動推斷的 SchemaConfig 以及各欄位的詳細推斷資訊，
    可匯出為 YAML 草稿供人工確認後正式使用。

    Attributes:
        schema_config: 推斷產出的 SchemaConfig
        inference_results: 各欄位的詳細推斷結果（順序與 schema_config.columns 對應）
        source_file: 來源檔案名稱（僅用於顯示）
        inferred_at: 推斷時間

    Example:
        >>> draft = discovery.infer('./bank.xlsx')
        >>> print(draft.summary())
        >>> draft.to_yaml('./config/schemas/bank_recon/bank_a_draft.yaml')
    """

    schema_config: SchemaConfig
    inference_results: list[ColumnInferenceResult]
    source_file: str
    inferred_at: datetime = field(default_factory=datetime.now)

    def to_yaml(self, path: str | Path) -> None:
        """
        匯出草稿 YAML 至指定路徑

        輸出格式與 SchemaConfig.from_yaml() 相容，可直接載入使用。
        YAML 檔頭包含推斷摘要注釋，請人工確認 source/target 對應與 dtype 後再正式使用。

        Args:
            path: 輸出 YAML 路徑，父目錄不存在時會自動建立

        Raises:
            ImportError: 未安裝 pyyaml 時拋出，請執行 pip install pyyaml
        """
        try:
            import yaml
        except ImportError:
            raise ImportError(
                "需要安裝 PyYAML 套件才能匯出 YAML。"
                "請執行: pip install pyyaml"
            )

        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        # 建構 YAML 資料（格式與 SchemaConfig.from_yaml() 相容）
        columns_data = []
        for col_spec, result in zip(self.schema_config.columns, self.inference_results):
            col_data: dict[str, Any] = {
                "source": col_spec.source,
                "target": col_spec.target,
                "dtype": col_spec.dtype,
                "required": col_spec.required,
            }
            if col_spec.default is not None:
                col_data["default"] = col_spec.default
            if col_spec.date_format is not None:
                col_data["date_format"] = col_spec.date_format
            columns_data.append(col_data)

        yaml_data = {
            "columns": columns_data,
            "circuit_breaker_threshold": self.schema_config.circuit_breaker_threshold,
            "filter_empty_rows": self.schema_config.filter_empty_rows,
            "preserve_unmapped": self.schema_config.preserve_unmapped,
        }

        # 產生檔頭注釋
        header_lines = [
            "# [推斷草稿，請人工確認]",
            f"# 來源: {self.source_file}",
            f"# 推斷時間: {self.inferred_at.strftime('%Y-%m-%d %H:%M:%S')}",
            "# 注意: source/target 對應、dtype、required 欄位請依實際需求調整",
            "#",
            "# 各欄位推斷摘要:",
        ]
        for result in self.inference_results:
            samples_str = ", ".join(str(v) for v in result.sample_values[:3])
            header_lines.append(
                f"#   {result.source}: {result.suggested_dtype} "
                f"(信心: {result.confidence:.0%}, "
                f"null_rate: {result.null_rate:.1%}, "
                f"樣本: [{samples_str}])"
            )
        header_lines.append("")

        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(header_lines) + "\n")
            yaml.dump(
                yaml_data,
                f,
                allow_unicode=True,
                default_flow_style=False,
                sort_keys=False,
            )

    def to_schema_config(self) -> SchemaConfig:
        """
        取得推斷產出的 SchemaConfig

        Returns:
            SchemaConfig: 可直接傳入 MetadataBuilder.build() 的 Schema 物件
        """
        return self.schema_config

    def summary(self) -> str:
        """
        產生人可讀的推斷摘要字串

        Returns:
            str: 格式化的摘要，包含各欄位名稱、推斷型別、信心度、null_rate、建議 required
        """
        lines = [
            f"Schema 推斷摘要 (來源: {self.source_file})",
            f"推斷時間: {self.inferred_at.strftime('%Y-%m-%d %H:%M:%S')}",
            f"欄位數量: {len(self.inference_results)}",
            "-" * 72,
            f"{'欄位名稱':<20} {'推斷型別':<12} {'信心度':>6} {'null_rate':>10} {'建議 required':>14}",
            "-" * 72,
        ]
        for result in self.inference_results:
            lines.append(
                f"{result.source:<20} {result.suggested_dtype:<12} "
                f"{result.confidence:>5.0%} {result.null_rate:>10.1%} "
                f"{'是' if result.suggested_required else '否':>14}"
            )
        lines.append("-" * 72)
        return "\n".join(lines)


class SchemaDiscovery:
    """
    Schema 自動探索工具

    從源檔案（Excel/CSV 等）自動推斷欄位型別，產出 SchemaConfig 草稿，
    減少接收新需求時手動逆向工程 Excel 欄位的時間。

    型別推斷優先順序：BOOLEAN → BIGINT → DOUBLE → DATETIME → DATE → VARCHAR

    Example:
        >>> from seafin_metadata_builder import SchemaDiscovery
        >>>
        >>> discovery = SchemaDiscovery()
        >>> draft = discovery.infer(
        ...     './bank_statement.xlsx',
        ...     sheet_name=0,
        ...     header_row=2,
        ...     sample_rows=100
        ... )
        >>> print(draft.summary())
        >>> draft.to_yaml('./config/schemas/bank_recon/bank_a_draft.yaml')
    """

    # 視為布林值的字串集合（比對時忽略大小寫）
    _BOOLEAN_VALUES: frozenset[str] = frozenset(
        {"true", "false", "yes", "no", "1", "0", "是", "否"}
    )

    def __init__(self, logger: logging.Logger = None):
        """
        初始化 SchemaDiscovery

        Args:
            logger: 外部日誌器，None 時使用模組內建日誌器
        """
        self.logger = logger or logging.getLogger(__name__)
        self._reader = SourceReader(logger=self.logger)

    def infer(
        self,
        file_path: str | Path,
        sheet_name: str | int = 0,
        header_row: int = 0,
        sample_rows: int = 100,
        required_threshold: float = 0.05,
    ) -> SchemaDraft:
        """
        從源檔案自動推斷 SchemaConfig 草稿

        Args:
            file_path: 來源檔案路徑（支援 Excel/CSV/Parquet/JSON）
            sheet_name: Excel Sheet 名稱或索引（預設 0）
            header_row: Header 所在行（0-indexed，預設 0）
            sample_rows: 用於推斷的最大樣本行數（預設 100，避免大檔案過慢）
            required_threshold: null_rate 低於此值時建議設為 required（預設 0.05）

        Returns:
            SchemaDraft: 草稿物件，可呼叫 to_yaml() 匯出或 summary() 檢視摘要

        Raises:
            SourceFileError: 檔案不存在或讀取失敗

        Example:
            >>> draft = discovery.infer('./bank.xlsx', sheet_name='Sheet1', header_row=2)
            >>> draft.to_yaml('./schema_draft.yaml')
        """
        file_path = Path(file_path)
        spec = SourceSpec(
            sheet_name=sheet_name,
            header_row=header_row,
            read_as_string=True,
        )

        self.logger.info(f"開始推斷 Schema: {file_path.name}")
        df = self._reader.read(file_path, spec)

        # 只取前 sample_rows 行
        if len(df) > sample_rows:
            df = df.head(sample_rows)
            self.logger.debug(f"截取前 {sample_rows} 行進行型別推斷")

        inference_results = [
            self._infer_column(str(col_name), df[col_name], required_threshold)
            for col_name in df.columns
        ]

        columns = [
            ColumnSpec(
                source=result.source,
                target=_normalize_column_name(result.source),
                dtype=result.suggested_dtype,
                required=result.suggested_required,
            )
            for result in inference_results
        ]

        schema_config = SchemaConfig(columns=columns)

        self.logger.info(
            f"Schema 推斷完成: {len(columns)} 欄位，來源: {file_path.name}"
        )

        return SchemaDraft(
            schema_config=schema_config,
            inference_results=inference_results,
            source_file=file_path.name,
        )

    def _infer_column(
        self,
        col_name: str,
        series: pd.Series,
        required_threshold: float,
    ) -> ColumnInferenceResult:
        """
        推斷單欄的型別與統計資訊

        Args:
            col_name: 欄位名稱
            series: 原始字串 Series（來自 SourceReader，dtype='string'）
            required_threshold: null_rate 低於此值時建議設為 required

        Returns:
            ColumnInferenceResult: 該欄位的推斷結果
        """
        # 計算空值率（pd.NA 和空字串都算）
        is_null = series.isna() | (series.astype(str).str.strip() == "")
        null_count = int(is_null.sum())
        total = len(series)
        null_rate = null_count / total if total > 0 else 1.0

        # 取得非空值的清理後字串
        non_null = series[~is_null].astype(str).str.strip()
        non_null_count = len(non_null)

        # 取樣本值（最多 5 個）
        sample_values: list[Any] = non_null.head(5).tolist()

        # 全空欄位：無法推斷，預設 VARCHAR
        if non_null_count == 0:
            return ColumnInferenceResult(
                source=col_name,
                suggested_dtype="VARCHAR",
                null_rate=null_rate,
                sample_values=[],
                suggested_required=False,
                confidence=1.0,
            )

        dtype, confidence = self._try_infer_dtype(non_null)

        return ColumnInferenceResult(
            source=col_name,
            suggested_dtype=dtype,
            null_rate=null_rate,
            sample_values=sample_values,
            suggested_required=null_rate < required_threshold,
            confidence=confidence,
        )

    def _try_infer_dtype(self, non_null: pd.Series) -> tuple[str, float]:
        """
        依優先順序嘗試推斷型別

        推斷順序：BOOLEAN → BIGINT → DOUBLE → DATETIME → DATE → VARCHAR

        Args:
            non_null: 已過濾空值的字串 Series

        Returns:
            tuple[str, float]: (dtype 字串, confidence 信心度 0.0~1.0)
        """
        n = len(non_null)

        # 1. BOOLEAN：所有非空值均在布林字串集合中
        lowered = non_null.str.lower()
        if lowered.isin(self._BOOLEAN_VALUES).sum() == n:
            return "BOOLEAN", 1.0

        # 2. BIGINT / DOUBLE：嘗試數值轉換
        numeric = pd.to_numeric(non_null, errors="coerce")
        numeric_success = int(numeric.notna().sum())
        numeric_rate = numeric_success / n

        if numeric_rate >= 0.9:
            # 無小數部分 → BIGINT，有小數 → DOUBLE
            if (numeric.dropna() % 1 == 0).all():
                return "BIGINT", numeric_rate
            return "DOUBLE", numeric_rate

        # 3. DATETIME / DATE：嘗試日期時間轉換
        parsed_dt = pd.to_datetime(non_null, errors="coerce", format="mixed")
        dt_success = int(parsed_dt.notna().sum())
        dt_rate = dt_success / n

        if dt_rate >= 0.8:
            # 含非零時間部分 → DATETIME，否則 → DATE
            has_time = parsed_dt.dropna().apply(
                lambda x: x.hour != 0 or x.minute != 0 or x.second != 0
            ).any()
            if has_time:
                return "DATETIME", dt_rate
            return "DATE", dt_rate

        # 4. VARCHAR fallback
        return "VARCHAR", 1.0


def _normalize_column_name(name: str) -> str:
    """
    將欄位名稱標準化為合法的 Python 識別符（小寫）

    規則：
    - 非字母數字字元（含中文）替換為底線
    - 前置數字加 _ 前綴
    - 合併連續底線，移除首尾底線
    - 結果為全小寫

    Args:
        name: 原始欄位名稱

    Returns:
        str: 標準化後的識別符，空字串時回傳 "col"
    """
    # 非字母數字字元（含中文、空格、特殊符號）→ 底線
    normalized = re.sub(r"[^\w]", "_", name, flags=re.UNICODE)
    # 合併連續底線，移除首尾底線
    normalized = re.sub(r"_+", "_", normalized).strip("_")
    # 前置數字加底線前綴（strip 後再處理，避免被移除）
    if normalized and normalized[0].isdigit():
        normalized = "_" + normalized
    return normalized.lower() if normalized else "col"
