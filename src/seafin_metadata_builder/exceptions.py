"""
Metadata Builder 自定義異常模組

所有異常類都以 MetadataBuilder 前綴命名，避免與其他模組衝突。
"""


class MetadataBuilderError(Exception):
    """Metadata Builder 基礎異常類"""
    pass


class SourceFileError(MetadataBuilderError):
    """
    源檔案讀取錯誤

    Attributes:
        file_path: 檔案路徑
        message: 錯誤訊息
    """

    def __init__(self, file_path: str, message: str = None):
        self.file_path = file_path
        self.message = message or f"無法讀取源檔案: {file_path}"
        super().__init__(self.message)


class SheetNotFoundError(SourceFileError):
    """Sheet 不存在錯誤"""

    def __init__(self, file_path: str, sheet_name: str):
        self.sheet_name = sheet_name
        super().__init__(
            file_path,
            f"在 '{file_path}' 中找不到 Sheet '{sheet_name}'"
        )


class SchemaValidationError(MetadataBuilderError):
    """
    Schema 驗證失敗

    Attributes:
        missing_columns: 缺失的必要欄位
        message: 錯誤訊息
    """

    def __init__(self, missing_columns: list[str], message: str = None):
        self.missing_columns = missing_columns
        self.message = message or f"缺少必要欄位: {missing_columns}"
        super().__init__(self.message)


class CircuitBreakerError(MetadataBuilderError):
    """
    Circuit Breaker 觸發錯誤 (NULL 比例超過閾值)

    Attributes:
        tripped_columns: 觸發的欄位
        null_ratios: 各欄位的 NULL 比例
        threshold: 閾值
    """

    def __init__(
        self,
        tripped_columns: list[str],
        null_ratios: dict[str, float],
        threshold: float
    ):
        self.tripped_columns = tripped_columns
        self.null_ratios = null_ratios
        self.threshold = threshold
        
        details = ", ".join(
            f"{col}: {ratio:.1%}" 
            for col, ratio in null_ratios.items() 
            if col in tripped_columns
        )
        self.message = (
            f"Circuit Breaker 觸發！以下欄位 NULL 比例超過 {threshold:.0%}: {details}"
        )
        super().__init__(self.message)


class TypeCastingError(MetadataBuilderError):
    """
    類型轉換錯誤

    Attributes:
        column_name: 欄位名稱
        target_type: 目標類型
        failed_count: 失敗筆數
    """

    def __init__(self, column_name: str, target_type: str, failed_count: int):
        self.column_name = column_name
        self.target_type = target_type
        self.failed_count = failed_count
        self.message = (
            f"欄位 '{column_name}' 有 {failed_count} 筆資料"
            f"無法轉換為 {target_type}"
        )
        super().__init__(self.message)


class ColumnMappingError(MetadataBuilderError):
    """
    欄位映射錯誤

    Attributes:
        source_pattern: 來源欄位 pattern
        available_columns: 可用的欄位列表
        reason: 失敗原因（可選，用於 regex 語法錯誤等情況）
    """

    def __init__(self, source_pattern: str, available_columns: list[str], reason: str = None):
        self.source_pattern = source_pattern
        self.available_columns = available_columns
        self.reason = reason
        if reason:
            self.message = f"欄位映射失敗 '{source_pattern}': {reason}"
        else:
            self.message = (
                f"找不到匹配 '{source_pattern}' 的欄位。"
                f"可用欄位: {available_columns[:10]}"
                + ("..." if len(available_columns) > 10 else "")
            )
        super().__init__(self.message)
