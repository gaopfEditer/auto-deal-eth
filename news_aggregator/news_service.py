#!/usr/bin/env python3
"""
热门资讯聚合服务
获取国际局势、经济、科技、美国经济事件等热门资讯
"""

import json
import re
import urllib.request
import urllib.parse
from datetime import datetime
from typing import List, Dict, Optional
import xml.etree.ElementTree as ET

class NewsAggregator:
    """新闻聚合器 - 从多个来源获取热门资讯"""
    
    def __init__(self):
        self.sources = {
            "international": [
                {"name": "BBC中文", "url": "https://www.bbc.com/zhongwen/simp/world/index.xml"},
                {"name": "路透中文网", "url": "https://cn.reuters.com/rssFeed/worldNews/"},
            ],
            "economy": [
                {"name": "路透财经", "url": "https://cn.reuters.com/rssFeed/businessNews/"},
                {"name": "华尔街日报", "url": "https://cn.wsj.com/zh-hans/rss.xml"},
            ],
            "tech": [
                {"name": "TechCrunch", "url": "https://techcrunch.com/feed/"},
                {"name": "The Verge", "url": "https://www.theverge.com/rss/index.xml"},
            ],
            "us_economy": [
                {"name": "Bloomberg", "url": "https://feeds.bloomberg.com/business/news.rss"},
                {"name": "CNBC", "url": "https://www.cnbc.com/id/100003114/device/rss/rss.html"},
            ]
        }
    
    def fetch_rss(self, url: str, limit: int = 5) -> List[Dict]:
        """获取 RSS 订阅源的新闻"""
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            }
            request = urllib.request.Request(url, headers=headers)
            
            with urllib.request.urlopen(request, timeout=15) as response:
                content = response.read()
                
            # 尝试解析 XML
            root = ET.fromstring(content)
            
            # 处理 RSS 2.0 和 Atom 格式
            items = []
            
            # RSS 2.0 格式
            for item in root.findall('.//item'):
                title = item.find('title')
                link = item.find('link')
                desc = item.find('description')
                pub_date = item.find('pubDate')
                
                if title is not None:
                    items.append({
                        'title': self._clean_text(title.text) if title.text else '',
                        'link': link.text if link is not None and link.text else '',
                        'description': self._clean_text(desc.text) if desc is not None and desc.text else '',
                        'published': pub_date.text if pub_date is not None else ''
                    })
                
                if len(items) >= limit:
                    break
            
            # Atom 格式
            if not items:
                ns = {'atom': 'http://www.w3.org/2005/Atom'}
                for entry in root.findall('.//atom:entry', ns):
                    title = entry.find('atom:title', ns)
                    link = entry.find('atom:link', ns)
                    summary = entry.find('atom:summary', ns)
                    updated = entry.find('atom:updated', ns)
                    
                    if title is not None:
                        link_href = link.get('href') if link is not None else ''
                        items.append({
                            'title': self._clean_text(title.text) if title.text else '',
                            'link': link_href,
                            'description': self._clean_text(summary.text) if summary is not None and summary.text else '',
                            'published': updated.text if updated is not None else ''
                        })
                    
                    if len(items) >= limit:
                        break
            
            return items
            
        except Exception as e:
            return [{'error': f'获取失败: {str(e)}', 'title': '获取失败', 'link': url}]
    
    def _clean_text(self, text: str) -> str:
        """清理文本内容"""
        if not text:
            return ''
        # 移除 HTML 标签
        text = re.sub(r'<[^>]+>', '', text)
        # 移除多余空白
        text = ' '.join(text.split())
        return text.strip()
    
    def fetch_category(self, category: str, limit: int = 5) -> Dict:
        """获取某一类别的所有新闻"""
        if category not in self.sources:
            return {'error': f'未知类别: {category}'}
        
        results = []
        for source in self.sources[category]:
            news_items = self.fetch_rss(source['url'], limit)
            results.append({
                'source': source['name'],
                'items': news_items
            })
        
        return {
            'category': category,
            'sources': results,
            'timestamp': datetime.now().isoformat()
        }
    
    def fetch_all(self, limit: int = 5) -> Dict:
        """获取所有类别的热门资讯"""
        results = {}
        for category in self.sources.keys():
            results[category] = self.fetch_category(category, limit)
        
        return {
            'all_news': results,
            'generated_at': datetime.now().isoformat()
        }
    
    def format_news(self, data: Dict) -> str:
        """格式化新闻输出为可读文本"""
        lines = []
        lines.append("=" * 60)
        lines.append("📰 热门资讯汇总")
        lines.append(f"⏰ 生成时间: {data.get('generated_at', 'N/A')}")
        lines.append("=" * 60)
        
        category_names = {
            'international': '🌍 国际局势',
            'economy': '💰 全球经济',
            'tech': '🔬 科技动态',
            'us_economy': '🇺🇸 美国经济事件'
        }
        
        for category, cat_data in data.get('all_news', {}).items():
            lines.append(f"\n{'─' * 60}")
            lines.append(f"{category_names.get(category, category)}")
            lines.append('─' * 60)
            
            for source in cat_data.get('sources', []):
                lines.append(f"\n📌 {source['source']}:")
                
                for item in source.get('items', []):
                    if 'error' in item:
                        lines.append(f"   ⚠️ {item['error']}")
                        continue
                    
                    title = item.get('title', '无标题')
                    link = item.get('link', '')
                    desc = item.get('description', '')
                    
                    lines.append(f"   • {title}")
                    if desc and len(desc) > 10:
                        # 截断过长的描述
                        short_desc = desc[:100] + '...' if len(desc) > 100 else desc
                        lines.append(f"     {short_desc}")
                    if link:
                        lines.append(f"     🔗 {link}")
                    lines.append("")
        
        lines.append("\n" + "=" * 60)
        return '\n'.join(lines)


def main():
    """主函数 - 命令行入口"""
    import argparse
    import sys
    
    # 设置 Windows 控制台 UTF-8 编码
    if sys.platform == 'win32':
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')
    
    parser = argparse.ArgumentParser(description='热门资讯聚合服务')
    parser.add_argument('--category', '-c', choices=['international', 'economy', 'tech', 'us_economy', 'all'],
                       default='all', help='选择新闻类别 (默认: all)')
    parser.add_argument('--limit', '-l', type=int, default=5, help='每个来源获取的新闻数量 (默认: 5)')
    parser.add_argument('--json', '-j', action='store_true', help='输出 JSON 格式')
    parser.add_argument('--output', '-o', help='输出到文件')
    
    args = parser.parse_args()
    
    aggregator = NewsAggregator()
    
    # 获取新闻
    if args.category == 'all':
        data = aggregator.fetch_all(args.limit)
    else:
        data = {'all_news': {args.category: aggregator.fetch_category(args.category, args.limit)},
                'generated_at': __import__('datetime').datetime.now().isoformat()}
    
    # 格式化输出
    if args.json:
        output = json.dumps(data, ensure_ascii=False, indent=2)
    else:
        output = aggregator.format_news(data)
    
    # 输出
    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            f.write(output)
        print(f"✅ 新闻已保存到: {args.output}")
    else:
        print(output)


if __name__ == '__main__':
    main()
