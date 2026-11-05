# -*- coding: utf-8 -*-
"""
xAgent.core.types —— 纯数据类型定义，无任何运行时依赖。

ToolResult  统一返回结构（dataclass + to_dict 互转，保证各前端可序列化）
ToolInfo    工具元数据（用于 UI 渲染工具列表、参数表单）
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, Optional


@dataclass
class ToolResult:
    """所有工具函数的统一返回结构。"""

    success: bool
    message: Optional[str] = None
    error: Optional[str] = None
    data: Dict[str, Any] = field(default_factory=dict)

    # ---------- 便捷构造 ----------
    @classmethod
    def ok(cls, message: str = "", **data: Any) -> "ToolResult":
        return cls(success=True, message=message, data=dict(data))

    @classmethod
    def fail(cls, error: str) -> "ToolResult":
        return cls(success=False, error=error)

    # ---------- 序列化 ----------
    def to_dict(self) -> Dict[str, Any]:
        """扁平化字典，保持和旧版 dict 返回兼容。"""
        flat: Dict[str, Any] = {"success": self.success}
        if self.message is not None:
            flat["message"] = self.message
        if self.error is not None:
            flat["error"] = self.error
        flat.update(self.data)
        return flat

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "ToolResult":
        raw = dict(raw)
        success = raw.pop("success", True)
        message = raw.pop("message", None)
        error = raw.pop("error", None)
        return cls(success=bool(success), message=message, error=error, data=raw)


@dataclass
class ToolInfo:
    """单个工具的元数据，用于 UI 渲染、自动生成参数表单。"""

    name: str
    description: str
    parameters: Dict[str, str] = field(default_factory=dict)  # param_name -> "type: description"

    # ---------- 便捷 ----------
    @property
    def param_names(self) -> list[str]:
        return list(self.parameters.keys())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
