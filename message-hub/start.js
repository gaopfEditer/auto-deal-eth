/**
 * Message Hub 客户端启动脚本
 * 提供多种启动选项
 */

const { exec } = require('child_process');
const path = require('path');
const fs = require('fs');

const LOG_FILE = path.join(__dirname, 'start.log');

function log(message, data = null) {
    const timestamp = new Date().toISOString();
    const logEntry = `[${timestamp}] ${message}` + (data ? ` ${JSON.stringify(data)}` : '');
    
    console.log(logEntry);
    
    try {
        fs.appendFileSync(LOG_FILE, logEntry + '\n', 'utf8');
    } catch (err) {
        console.error(`写入日志失败: ${err.message}`);
    }
}

function showHelp() {
    console.log(`
Message Hub 客户端启动脚本

用法:
  node start.js [选项]

选项:
  --executor      启动通用执行器 (默认)
  --openclaw      启动 OpenClaw 专用执行器
  --test          运行测试
  --help          显示此帮助信息

环境变量:
  EXECUTOR_ID     执行器唯一标识
  WS_URL          WebSocket 服务器地址
  WEBHOOK_URL     Webhook 结果回调地址
  LOG_FILE        日志文件路径

示例:
  node start.js --executor
  EXECUTOR_ID=my_executor node start.js --openclaw
  WS_URL=ws://example.com/api/ws?type=openclaw node start.js --test
`);
}

function runExecutor() {
    log('启动通用执行器');
    const executorPath = path.join(__dirname, 'executor.js');
    
    const env = {
        ...process.env,
        EXECUTOR_ID: process.env.EXECUTOR_ID || 'executor_js',
        WS_URL: process.env.WS_URL || 'ws://localhost:3123/api/ws?type=openclaw',
        WEBHOOK_URL: process.env.WEBHOOK_URL || 'http://localhost:3123/api/openclaw/webhook'
    };
    
    const child = exec(`node "${executorPath}"`, { env });
    
    child.stdout.on('data', (data) => {
        process.stdout.write(data);
    });
    
    child.stderr.on('data', (data) => {
        process.stderr.write(data);
    });
    
    child.on('close', (code) => {
        log(`通用执行器退出，代码: ${code}`);
        process.exit(code);
    });
}

function runOpenClawExecutor() {
    log('启动 OpenClaw 专用执行器');
    const executorPath = path.join(__dirname, 'openclaw_executor.js');
    
    const env = {
        ...process.env,
        EXECUTOR_ID: process.env.EXECUTOR_ID || 'openclaw_executor',
        WS_URL: process.env.WS_URL || 'ws://localhost:3123/api/ws?type=openclaw',
        WEBHOOK_URL: process.env.WEBHOOK_URL || 'http://localhost:3123/api/openclaw/webhook'
    };
    
    const child = exec(`node "${executorPath}"`, { env });
    
    child.stdout.on('data', (data) => {
        process.stdout.write(data);
    });
    
    child.stderr.on('data', (data) => {
        process.stderr.write(data);
    });
    
    child.on('close', (code) => {
        log(`OpenClaw 执行器退出，代码: ${code}`);
        process.exit(code);
    });
}

function runTest() {
    log('运行测试');
    const testPath = path.join(__dirname, 'test.js');
    
    const env = {
        ...process.env,
        PORT: process.env.PORT || '3123'
    };
    
    const child = exec(`node "${testPath}"`, { env });
    
    child.stdout.on('data', (data) => {
        process.stdout.write(data);
    });
    
    child.stderr.on('data', (data) => {
        process.stderr.write(data);
    });
    
    child.on('close', (code) => {
        log(`测试退出，代码: ${code}`);
        process.exit(code);
    });
}

// 解析命令行参数
const args = process.argv.slice(2);
const option = args[0] || '--executor';

switch (option) {
    case '--executor':
        runExecutor();
        break;
    case '--openclaw':
        runOpenClawExecutor();
        break;
    case '--test':
        runTest();
        break;
    case '--help':
    case '-h':
        showHelp();
        process.exit(0);
        break;
    default:
        console.error(`未知选项: ${option}`);
        showHelp();
        process.exit(1);
}
