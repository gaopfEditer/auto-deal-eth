#!/usr/bin/env node
/**
 * message-hub 自动重启守护进程
 * 保持 WebSocket 连接，断开时自动重连
 */

const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs');

class AutoRestartExecutor {
    constructor() {
        this.scriptPath = path.join(__dirname, 'executor.js');
        this.logFile = path.join(__dirname, 'auto-restart.log');
        this.maxRetries = 10;
        this.retryDelay = 5000; // 5秒
        this.childProcess = null;
        this.retryCount = 0;
        this.isRunning = false;
        
        this.setupLogging();
    }
    
    setupLogging() {
        // 确保日志文件存在
        if (!fs.existsSync(this.logFile)) {
            fs.writeFileSync(this.logFile, '');
        }
    }
    
    log(message, level = 'INFO') {
        const timestamp = new Date().toISOString();
        const logEntry = `[${timestamp}] [${level}] ${message}\n`;
        
        console.log(logEntry.trim());
        fs.appendFileSync(this.logFile, logEntry, 'utf8');
    }
    
    start() {
        this.log('🚀 启动 message-hub 自动重启守护进程');
        this.isRunning = true;
        this.startProcess();
        
        // 监听进程退出
        process.on('SIGINT', () => this.shutdown());
        process.on('SIGTERM', () => this.shutdown());
    }
    
    startProcess() {
        if (!this.isRunning) return;
        
        this.log(`启动子进程 (尝试 ${this.retryCount + 1}/${this.maxRetries})`);
        
        // 设置环境变量
        const env = {
            ...process.env,
            EXECUTOR_ID: `message_hub_auto_${Date.now()}`,
            WS_URL: 'ws://localhost:3123/api/ws?type=openclaw',
            WEBHOOK_URL: 'http://localhost:3123/api/openclaw/webhook',
            LOG_FILE: path.join(__dirname, 'message-hub-client.log')
        };
        
        this.childProcess = spawn('node', [this.scriptPath], {
            env: env,
            stdio: ['pipe', 'pipe', 'pipe']
        });
        
        // 处理输出
        this.childProcess.stdout.on('data', (data) => {
            const output = data.toString().trim();
            if (output) {
                this.log(`[子进程输出] ${output}`);
            }
        });
        
        this.childProcess.stderr.on('data', (data) => {
            const error = data.toString().trim();
            if (error) {
                this.log(`[子进程错误] ${error}`, 'ERROR');
            }
        });
        
        // 处理退出
        this.childProcess.on('close', (code) => {
            this.log(`子进程退出，代码: ${code}`);
            this.childProcess = null;
            
            if (this.isRunning) {
                if (this.retryCount < this.maxRetries) {
                    this.retryCount++;
                    this.log(`等待 ${this.retryDelay / 1000} 秒后重试...`);
                    setTimeout(() => this.startProcess(), this.retryDelay);
                } else {
                    this.log(`已达到最大重试次数 (${this.maxRetries})，停止重试`, 'ERROR');
                    this.shutdown();
                }
            }
        });
        
        this.childProcess.on('error', (err) => {
            this.log(`子进程错误: ${err.message}`, 'ERROR');
        });
    }
    
    shutdown() {
        this.log('🛑 停止守护进程...');
        this.isRunning = false;
        
        if (this.childProcess) {
            this.log('终止子进程...');
            this.childProcess.kill('SIGTERM');
            
            // 强制终止如果 5 秒后还在运行
            setTimeout(() => {
                if (this.childProcess) {
                    this.childProcess.kill('SIGKILL');
                }
            }, 5000);
        }
        
        this.log('守护进程已停止');
        process.exit(0);
    }
    
    restart() {
        this.log('🔄 重启子进程...');
        this.retryCount = 0;
        
        if (this.childProcess) {
            this.childProcess.kill('SIGTERM');
        } else {
            this.startProcess();
        }
    }
}

// 主函数
if (require.main === module) {
    const daemon = new AutoRestartExecutor();
    
    // 处理命令行参数
    const command = process.argv[2];
    
    switch (command) {
        case 'start':
            daemon.start();
            break;
        case 'restart':
            daemon.restart();
            break;
        case 'stop':
            daemon.shutdown();
            break;
        default:
            console.log('📖 message-hub 自动重启守护进程');
            console.log('使用方法:');
            console.log('  node auto-restart.js start    # 启动守护进程');
            console.log('  node auto-restart.js restart  # 重启子进程');
            console.log('  node auto-restart.js stop     # 停止守护进程');
            console.log('\n功能:');
            console.log('  • 自动启动 message-hub 执行器');
            console.log('  • 进程崩溃时自动重启');
            console.log('  • 最大重试次数: 10 次');
            console.log('  • 重试延迟: 5 秒');
            console.log('  • 日志文件: auto-restart.log');
            break;
    }
}

module.exports = AutoRestartExecutor;
