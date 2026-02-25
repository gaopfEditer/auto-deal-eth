# 设置本机代理为 7890（需在终端执行 source set_proxy_7890.sh）
# 使用 localhost 避免部分库解析 127.0.0.1 时报 "Failed to parse"
# 程序已使用 REST 传输，会走 HTTP_PROXY
export HTTP_PROXY=http://localhost:7890
export HTTPS_PROXY=http://localhost:7890
export http_proxy=http://localhost:7890
export https_proxy=http://localhost:7890
echo "已设置代理: localhost:7890"
echo "HTTP_PROXY=$HTTP_PROXY"
