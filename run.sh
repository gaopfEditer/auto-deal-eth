#!/bin/bash
# 运行脚本

# 激活虚拟环境（如果存在）
if [ -d "venv" ]; then
    source venv/bin/activate
fi

# 运行程序
python3 main.py "$@"
