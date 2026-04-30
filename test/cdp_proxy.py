"""
Chrome 136+ 的 /json/version 返回 400，Playwright 无法连接。
此代理将 /json/version 请求转为从 /json 获取数据并返回兼容格式。
用法: 在另一个终端运行 python test/cdp_proxy.py，然后连接 127.0.0.1:9223
"""
import json
import urllib.request
from http.server import HTTPServer, BaseHTTPRequestHandler

CDP_PORT = 9222
PROXY_PORT = 9223


def _build_version_response():
    """从 9222/json 构造 version 响应，绝不转发到 Chrome 的 /json/version（会 400）"""
    req = urllib.request.urlopen(f"http://127.0.0.1:{CDP_PORT}/json", timeout=5)
    data = json.loads(req.read().decode())
    item = data[0] if isinstance(data, list) and data else (data if isinstance(data, dict) else {})
    ws = (item.get("webSocketDebuggerUrl") or "").replace("localhost", "127.0.0.1")
    return json.dumps({
        "Browser": "Chrome/136.0",
        "Protocol-Version": "1.3",
        "User-Agent": "Chrome",
        "webSocketDebuggerUrl": ws,
    }).encode()


class CDPProxyHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        # 对任意请求都返回 version 响应，不转发（Chrome /json/version 返回 400）
        try:
            body = _build_version_response()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except Exception as e:
            self.send_response(502)
            self.send_header("Content-Length", "0")
            self.end_headers()

    def log_message(self, format, *args):
        pass


def run():
    server = HTTPServer(("127.0.0.1", PROXY_PORT), CDPProxyHandler)
    print(f"CDP 代理已启动: http://127.0.0.1:{PROXY_PORT} -> 127.0.0.1:{CDP_PORT}")
    print("请将 Playwright 连接至 127.0.0.1:9223")
    server.serve_forever()


if __name__ == "__main__":
    run()
