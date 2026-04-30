/**
 * message-hub 监控脚本
 * 用于 OpenClaw cron 任务，监控并确保 message-hub 在运行
 */

const { exec } = require('child_process');
const fs = require('fs');
const path = require('path');

class MessageHubMonitor {
    constructor() {
        this.logFile = path.join(__dirname, 'monitor.log');
        this.executorLog = path.join(__dirname, 'message-hub-client.log');
        this.setupLogging();
    }
    
    setupLogging() {
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
    
    async checkProcess() {
        return new Promise((resolve) => {
            // 检查是否有 node 进程运行 executor.js
            exec('tasklist /FI "IMAGENAME eq node.exe" /FO CSV', (error, stdout) => {
                if (error) {
                    this.log(`检查进程失败: ${error.message}`, 'ERROR');
                    resolve(false);
                    return;
                }
                
                const lines = stdout.split('\n');
                let isRunning = false;
                
                for (const line of lines) {
                    if (line.includes('executor.js') || line.includes('openclaw_executor.js')) {
                        isRunning = true;
                        break;
                    }
                }
                
                resolve(isRunning);
            });
        });
    }
    
    async startProcess() {
        this.log('启动 message-hub 进程...');
        
        return new Promise((resolve) => {
            const env = {
                ...process.env,
                EXECUTOR_ID: `message_hub_monitor_${Date.now()}`,
                WS_URL: 'ws://localhost:3123/api/ws?type=openclaw',
                WEBHOOK_URL: 'http://localhost:3123/api/openclaw/webhook',
                LOG_FILE: this.executorLog
            };
            
            const child = exec('node executor.js', {
                env: env,
                cwd: __dirname
            }, (error) => {
                if (error) {
                    this.log(`进程启动失败: ${error.message}`, 'ERROR');
                    resolve(false);
                }
            });
            
            // 记录进程输出
            child.stdout?.on('data', (data) => {
                const output = data.toString().trim();
                if (output) {
                    this.log(`[进程输出] ${output}`);
                }
            });
            
            child.stderr?.on('data', (data) => {
                const error = data.toString().trim();
                if (error) {
                    this.log(`[进程错误] ${error}`, 'ERROR');
                }
            });
            
            this.log(`进程已启动，PID: ${child.pid}`);
            resolve(true);
        });
    }
    
    async monitor() {
        this.log('开始监控 message-hub...');
        
        const isRunning = await this.checkProcess();
        
        if (!isRunning) {
            this.log('message-hub 未在运行，正在启动...', 'WARN');
            const started = await this.startProcess();
            
            if (started) {
                this.log('✅ message-hub 已成功启动');
                return {
                    status: 'restarted',
                    message: 'Message hub was not running and has been started'
                };
            } else {
                this.log('❌ message-hub 启动失败', 'ERROR');
                return {
                    status: 'failed',
                    message: 'Failed to start message hub'
                };
            }
        } else {
            this.log('✅ message-hub 正在运行');
            return {
                status: 'running',
                message: 'Message hub is running normally'
            };
        }
    }
}

// 主函数
async function main() {
    const monitor = new MessageHubMonitor();
    
    try {
        const result = await monitor.monitor();
        
        // 返回结果给 OpenClaw cron
        console.log(JSON.stringify(result, null, 2));
        
        if (result.status === 'failed') {
            process.exit(1);
        } else {
            process.exit(0);
        }
    } catch (error) {
        monitor.log(`监控失败: ${error.message}`, 'ERROR');
        console.error(JSON.stringify({
            status: 'error',
            message: error.message
        }, null, 2));
        process.exit(1);
    }
}

if (require.main === module) {
    main();
}

module.exports = MessageHubMonitor;
