"""
Gemini分析模块 - 第1部分：导入和初始化
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
        raise ValueError("❌ 错误：GEMINI_API_KEY 未配置！请在 .env 文件中设置 GEMINI_API_KEY")
    
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel(GEMINI_MODEL)
    return model

# 第2部分：图片处理和提示词
def load_image(image_path: str):
    """加载图片文件"""
    return Image.open(image_path)

def get_analysis_prompt():
    """获取分析提示词"""
    prompt = """
请分析以下K线图表，并按照JSON格式输出交易策略建议。

分析要求：
1. 识别当前趋势（上涨/下跌/震荡）
2. 识别关键支撑位和阻力位
3. 分析技术指标信号（如MACD、RSI、均线等）
4. 给出交易建议（买入/卖出/持有）
5. 评估风险等级（低/中/高）

请以JSON格式输出，包含以下字段：
{
    "trend": "趋势方向",
    "support_level": "支撑位",
    "resistance_level": "阻力位",
    "indicators": {
        "macd": "MACD信号",
        "rsi": "RSI值",
        "ma": "均线状态"
    },
    "recommendation": "交易建议",
    "risk_level": "风险等级",
    "reasoning": "分析理由"
}
"""
    return prompt

# 第3部分：多图分析和结果处理
def analyze_charts(model, image_paths: dict):
    """分析多个周期的K线图"""
    results = {}
    
    for timeframe, image_path in image_paths.items():
        try:
            print(f"正在分析 {timeframe} 周期...")
            image = load_image(image_path)
            prompt = get_analysis_prompt()
            
            # 调用Gemini API进行多模态分析
            response = model.generate_content([prompt, image])
            results[timeframe] = {
                'timeframe': timeframe,
                'analysis': response.text,
                'status': 'success'
            }
        except Exception as e:
            print(f"分析失败 {timeframe}: {e}")
            results[timeframe] = {
                'timeframe': timeframe,
                'analysis': None,
                'status': 'error',
                'error': str(e)
            }
    
    return results

def analyze_all_timeframes(image_paths: dict):
    """分析所有周期的图表"""
    model = init_gemini()
    return analyze_charts(model, image_paths)
