"""
Gemini分析模块 - 优化版
"""
try:
    import google.generativeai as genai
except ImportError:
    print("警告：google.generativeai 未安装，请运行: pip install google-generativeai")
    raise

import base64
from PIL import Image
from config import GEMINI_API_KEY, GEMINI_MODEL

def init_gemini():
    """初始化Gemini客户端"""
    if not GEMINI_API_KEY:
        raise ValueError("[ERROR] 错误：GEMINI_API_KEY 未配置！")
    
    genai.configure(api_key=GEMINI_API_KEY)
    
    # 1. 确保模型名称包含 'models/' 前缀 (解决 404 的关键)
    full_model_name = GEMINI_MODEL if GEMINI_MODEL.startswith("models/") else f"models/{GEMINI_MODEL}"
    
    try:
        # 2. 初始化模型时，针对 JSON 任务可以开启 schema 约束
        # 这里先使用通用初始化
        model = genai.GenerativeModel(
            model_name=full_model_name,
            generation_config={"response_mime_type": "application/json"}
        )
        print(f"[OK] 成功初始化模型: {full_model_name}")
        return model
    except Exception as e:
        print(f"[ERROR] 模型 {full_model_name} 初始化失败: {e}")
        
        # 备用模型列表，全部带上 models/ 前缀
        fallback_models = [
            'models/gemini-2.0-flash', 
            'models/gemini-1.5-flash', 
            'models/gemini-1.5-pro'
        ]
        
        for fallback in fallback_models:
            if fallback != full_model_name:
                try:
                    print(f"[INFO] 尝试使用备用模型: {fallback}")
                    model = genai.GenerativeModel(
                        model_name=fallback,
                        generation_config={"response_mime_type": "application/json"}
                    )
                    print(f"[OK] 成功使用备用模型: {fallback}")
                    return model
                except Exception:
                    continue
        raise ValueError(f"[ERROR] 无法初始化任何模型。")

def get_analysis_prompt():
    """获取分析提示词 (优化了 prompt 以适配 JSON 模式)"""
    return """
你是一个资深的加密货币技术分析师。请分析提供的 K 线图表，并严格按照 JSON 格式输出建议。
分析要求：
1. 识别当前趋势（上涨/下跌/震荡）
2. 识别关键支撑位和阻力位
3. 分析技术指标信号（MACD, RSI, Bollinger Bands 等）
4. 给出明确交易建议（Long/Short/Neutral）
5. 评估风险等级（Low/Medium/High）

输出格式必须符合以下 JSON 结构：
{
    "trend": "string",
    "support_level": "string",
    "resistance_level": "string",
    "indicators": {
        "macd": "string",
        "rsi": "string",
        "bb": "string"
    },
    "recommendation": "string",
    "risk_level": "string",
    "reasoning": "string"
}
"""

def analyze_charts(model, image_paths: dict):
    """分析多个周期的K线图"""
    results = {}
    
    for timeframe, image_path in image_paths.items():
        try:
            print(f"正在分析 {timeframe} 周期...")
            # 使用 PIL 加载图片
            image = Image.open(image_path)
            prompt = get_analysis_prompt()
            
            # 核心调用
            response = model.generate_content([prompt, image])
            
            # 直接存储 JSON 结果
            results[timeframe] = {
                'timeframe': timeframe,
                'analysis': response.text,
                'status': 'success'
            }
        except Exception as e:
            # 如果报错，这里会打印具体的 API 错误信息
            print(f"[ERROR] 分析失败 {timeframe}: {str(e)}")
            results[timeframe] = {
                'timeframe': timeframe,
                'status': 'error',
                'error': str(e)
            }
    
    return results

def analyze_chart(combined_image_path: str, symbol: str):
    """分析图片（支持K线图和普通页面）"""
    try:
        model = init_gemini()
        
        # 加载图片
        image = Image.open(combined_image_path)
        
        # 根据symbol判断分析类型
        if symbol == "tophub" or "tophub" in symbol.lower():
            # 普通页面分析
            print(f"  正在分析页面内容...")
            prompt = f"""
请分析这个网页截图的内容，并严格按照 JSON 格式输出分析结果。

这是一个技术开发者热门内容聚合页面（tophub.today/c/developer）。

分析要求：
1. 识别页面上的主要内容类型和主题
2. 提取热门文章/项目的标题和关键信息
3. 分析当前技术趋势和热点话题
4. 总结页面上的重要信息
5. 提供有价值的洞察

输出格式必须符合以下 JSON 结构：
{{
    "page_type": "string",
    "main_topics": ["string"],
    "hot_items": [
        {{
            "title": "string",
            "description": "string",
            "category": "string"
        }}
    ],
    "trends": "string",
    "insights": "string",
    "summary": "string"
}}
"""
        else:
            # K线图分析
            print(f"  正在分析 {symbol} 组合图表...")
            prompt = f"""
你是一个资深的加密货币技术分析师。请分析提供的 K 线图表组合图，并严格按照 JSON 格式输出建议。

图表说明：
- 这是一张包含4个时间周期的组合图（2x2布局）
- 左上角：15分钟周期
- 右上角：30分钟周期
- 左下角：1小时周期
- 右下角：2小时周期
- 币种：{symbol}

分析要求：
1. 识别当前趋势（上涨/下跌/震荡）
2. 识别关键支撑位和阻力位
3. 分析技术指标信号（MACD, RSI, Bollinger Bands 等）
4. 综合4个周期的分析，给出明确交易建议（Long/Short/Neutral）
5. 评估风险等级（Low/Medium/High）

输出格式必须符合以下 JSON 结构：
{{
    "symbol": "{symbol}",
    "trend": "string",
    "support_level": "string",
    "resistance_level": "string",
    "indicators": {{
        "macd": "string",
        "rsi": "string",
        "bb": "string"
    }},
    "recommendation": "string",
    "risk_level": "string",
    "reasoning": "string"
}}
"""
        
        # 调用Gemini API
        response = model.generate_content([prompt, image])
        
        return {
            'symbol': symbol,
            'analysis': response.text,
            'status': 'success'
        }
    except Exception as e:
        print(f"[ERROR] {symbol} 分析失败: {str(e)}")
        return {
            'symbol': symbol,
            'status': 'error',
            'error': str(e)
        }

def analyze_all_timeframes(image_paths: dict):
    """主入口（兼容旧接口）"""
    model = init_gemini()
    return analyze_charts(model, image_paths)