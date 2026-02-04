# Windows 安装指南

## 问题说明

当前虚拟环境使用的是 MinGW 构建的 Python，与大多数预编译的 Python 包（如 `playwright`、`grpcio` 等）不兼容。

## 解决方案

### 方案 1：使用标准 Windows Python（推荐）

1. **下载并安装标准 Windows Python**
   - 访问 https://www.python.org/downloads/
   - 下载 Python 3.12 或更高版本
   - 安装时勾选 "Add Python to PATH"

2. **删除旧的虚拟环境并重新创建**
   ```powershell
   # 删除旧的虚拟环境
   Remove-Item -Recurse -Force venv
   
   # 使用标准 Python 创建新的虚拟环境
   python -m venv venv
   
   # 激活虚拟环境（PowerShell）
   .\venv\Scripts\Activate.ps1
   
   # 如果遇到执行策略错误，运行：
   Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
   
   # 或者使用 CMD 方式激活
   venv\Scripts\activate.bat
   ```

3. **安装依赖**
   ```powershell
   pip install -r requirements.txt
   ```

4. **安装 Playwright 浏览器**
   ```powershell
   playwright install chromium
   ```

### 方案 2：使用当前 Python（需要编译工具）

如果必须使用当前的 MinGW Python，需要安装编译工具：

1. **安装 Microsoft C++ Build Tools**
   - 下载：https://visualstudio.microsoft.com/visual-cpp-build-tools/
   - 安装时选择 "C++ build tools"

2. **安装 Rust（用于某些包的编译）**
   - 下载：https://www.rust-lang.org/tools/install

3. **从源码安装依赖**
   ```powershell
   venv\bin\python.exe -m pip install -r requirements.txt --no-binary :all:
   ```

## 当前已安装的包

以下包已成功安装：
- ✅ requests
- ✅ python-dotenv
- ✅ schedule

以下包需要标准 Python 才能安装：
- ❌ playwright（需要标准 Windows Python）
- ❌ google-generativeai（依赖 grpcio，需要标准 Windows Python）
- ❌ pillow（可能需要编译工具）

## 快速开始（使用标准 Python）

```powershell
# 1. 删除旧虚拟环境
Remove-Item -Recurse -Force venv

# 2. 创建新虚拟环境（使用标准 Python）
python -m venv venv

# 3. 激活虚拟环境
.\venv\Scripts\Activate.ps1

# 4. 安装依赖
pip install -r requirements.txt

# 5. 安装 Playwright 浏览器
playwright install chromium

# 6. 运行项目
python main.py --once
```

## 注意事项

- 如果 PowerShell 执行策略阻止运行脚本，使用 `venv\Scripts\activate.bat` 代替
- 确保使用标准 Windows Python（从 python.org 下载），而不是 MinGW 构建的版本
- 安装 Playwright 后需要单独安装浏览器：`playwright install chromium`

