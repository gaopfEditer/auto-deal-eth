#!/usr/bin/env bash
# 查看本机代理配置

echo "========== 环境变量 =========="
echo "HTTP_PROXY  = ${HTTP_PROXY:-未设置}"
echo "HTTPS_PROXY = ${HTTPS_PROXY:-未设置}"
echo "http_proxy  = ${http_proxy:-未设置}"
echo "https_proxy = ${https_proxy:-未设置}"
echo "NO_PROXY    = ${NO_PROXY:-未设置}"

echo ""
echo "========== 系统网络代理 (macOS) =========="
# 查看当前网络服务的代理（Wi-Fi 或 Ethernet）
networksetup -getwebproxy "Wi-Fi" 2>/dev/null || true
networksetup -getsecurewebproxy "Wi-Fi" 2>/dev/null || true
echo "（若需查看其他网络服务，可用: networksetup -listallnetworkservices）"

echo ""
echo "========== 测试连通性 =========="
echo -n "Google API: "
curl -s -o /dev/null -w "%{http_code}" --connect-timeout 3 https://generativelanguage.googleapis.com 2>/dev/null || echo "超时/失败"
echo ""
echo -n "百度:      "
curl -s -o /dev/null -w "%{http_code}" --connect-timeout 3 https://www.baidu.com 2>/dev/null || echo "超时/失败"
