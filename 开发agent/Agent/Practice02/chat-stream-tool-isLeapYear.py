# -*- coding: utf-8 -*-
"""
模板文件: chat-stream-tool-isLeapYear.py
展示如何以工具函数的形式提供功能，并支持交互式调用。
"""

import json
import sys


# ============ 工具函数定义 ============

def is_leap_year(year: int) -> dict:
    """
    判断指定年份是否为闰年。
    
    Args:
        year: 要判断的年份（整数）
    
    Returns:
        dict: 包含判断结果的字典
    """
    if not isinstance(year, int) or year <= 0:
        return {"success": False, "error": "年份必须是正整数"}
    
    if (year % 4 == 0 and year % 100 != 0) or (year % 400 == 0):
        return {"success": True, "year": year, "is_leap": True, "message": f"{year} 是闰年"}
    else:
        return {"success": True, "year": year, "is_leap": False, "message": f"{year} 不是闰年"}


# ============ 工具注册表 ============

TOOLS = {
    "is_leap_year": {
        "func": is_leap_year,
        "description": "判断指定年份是否为闰年",
        "parameters": {
            "year": "int: 要判断的年份"
        }
    }
}


# ============ 工具调用入口 ============

def call_tool(tool_name: str, **kwargs) -> dict:
    """
    调用指定的工具函数。
    
    Args:
        tool_name: 工具名称
        **kwargs: 传递给工具的参数
    
    Returns:
        dict: 工具执行结果
    """
    if tool_name not in TOOLS:
        return {"success": False, "error": f"未知工具: {tool_name}"}
    
    tool_info = TOOLS[tool_name]
    try:
        result = tool_info["func"](**kwargs)
        return result
    except Exception as e:
        return {"success": False, "error": str(e)}


# ============ 交互式主程序 ============

def main():
    """交互式主程序入口"""
    print("=" * 50)
    print("📋 可用工具列表:")
    for name, info in TOOLS.items():
        print(f"  - {name}: {info['description']}")
        print(f"    参数: {info['parameters']}")
    print("=" * 50)
    
    while True:
        try:
            print("\n请输入工具调用（输入 q 退出）:")
            print("格式示例: is_leap_year year=2024")
            user_input = input("> ").strip()
            
            if user_input.lower() == 'q':
                print("👋 退出程序")
                break
            
            # 解析输入
            parts = user_input.split()
            if len(parts) < 1:
                print("❌ 输入格式错误")
                continue
            
            tool_name = parts[0]
            params = {}
            for part in parts[1:]:
                if '=' in part:
                    key, val = part.split('=', 1)
                    # 尝试转换为整数
                    try:
                        params[key] = int(val)
                    except ValueError:
                        params[key] = val
            
            # 调用工具
            result = call_tool(tool_name, **params)
            print(f"\n✅ 结果:")
            print(json.dumps(result, ensure_ascii=False, indent=2))
            
        except KeyboardInterrupt:
            print("\n👋 退出程序")
            break
        except Exception as e:
            print(f"❌ 错误: {e}")


if __name__ == "__main__":
    main()
