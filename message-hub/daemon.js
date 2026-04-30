/**
 * message-hub 守护进程管理器
 * 使用 pm2 保持 WebSocket 连接在后台运行
 */

const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs');

class MessageHubDaemon {
    constructor() {
        this.pm2Path = path.join(__dirname, 'node_modules', '.bin', 'pm2');
        this.executorPath = path.join(__dirname, 'executor.js');
        this.openclawExecutorPath = path.join(__dirname, 'openclaw_executor.js');
        this.configPath = path.join(__dirname, 'pm2.config.js');
        this.logDir = path.join(__dirname, 'logs');
        
        this.ensureLogDir();
    }
    
    ensureLogDir() {
        if (!fs.existsSync(this.logDir)) {
            fs.createDirectorySync(this.logDir, { recursive: true });
        }
    }
    
    async start() {
        console.log('🚀 启动 message-hub 守护进程...');
        
        // 检查是否安装了 pm2
        if (!fs.existsSync(this.pm2Path)) {
            console.log('📦 安装 pm2...');
            await this.installPm2();
        }
        
        // 创建 pm2 配置文件
        this.createPm2Config();
        
        // 启动 pm2 进程
        return new Promise((resolve, reject) => {
            const pm2 = spawn('node', [this.pm2Path, 'start', this.configPath], {
                stdio: 'inherit',
                shell: true
            });
            
            pm2.on('close', (code) => {
                if (code === 0) {
                    console.log('✅ message-hub 守护进程已启动');
                    console.log('📋 运行以下命令管理进程:');
                    console.log('  node node_modules/.bin/pm2 status          # 查看状态');
                    console.log('  node node_modules/.bin/pm2 logs message-hub  # 查看日志');
                    console.log('  node node_modules/.bin/pm2 stop message-hub  # 停止');
                    console.log('  node node_modules/.bin/pm2 restart message-hub # 重启');
                    resolve();
                } else {
                    reject(new Error(`pm2 启动失败，代码: ${code}`));
                }
            });
            
            pm2.on('error', (err) => {
                reject(err);
            });
        });
    }
    
    async stop() {
        console.log('🛑 停止 message-hub 守护进程...');
        
        return new Promise((resolve, reject) => {
            const pm2 = spawn('node', [this.pm2Path, 'stop', 'message-hub'], {
                stdio: 'inherit',
                shell: true
            });
            
            pm2.on('close', (code) => {
                if (code === 0) {
                    console.log('✅ message-hub 守护进程已停止');
                    resolve();
                } else {
                    reject(new Error(`pm2 停止失败，代码: ${code}`));
                }
            });
            
            pm2.on('error', (err) => {
                reject(err);
            });
        });
    }
    
    async status() {
        console.log('📊 检查 message-hub 守护进程状态...');
        
        return new Promise((resolve, reject) => {
            const pm2 = spawn('node', [this.pm2Path, 'status'], {
                stdio: 'inherit',
                shell: true
            });
            
            pm2.on('close', (code) => {
                if (code === 0) {
                    resolve();
                } else {
                    reject(new Error(`pm2 状态检查失败，代码: ${code}`));
                }
            });
            
            pm2.on('error', (err) => {
                reject(err);
            });
        });
    }
    
    async installPm2() {
        return new Promise((resolve, reject) => {
            console.log('正在安装 pm2...');
            const npm = spawn('npm', ['install', 'pm2', '--save-dev'], {
                cwd: __dirname,
                stdio: 'inherit',
                shell: true
            });
            
            npm.on('close', (code) => {
                if (code === 0) {
                    console.log('✅ pm2 安装完成');
                    resolve();
                } else {
                    reject(new Error(`npm 安装失败，代码: ${code}`));
                }
            });
            
            npm.on('error', (err) => {
                reject(err);
            });
        });
    }
    
    createPm2Config() {
        const config = {
            apps: [{
                name: 'message-hub',
                script: this.executorPath,
                // 也可以使用 openclaw_executor.js
                // script: this.openclawExecutorPath,
                args: [],
                instances: 1,
                autorestart: true,
                watch: false,
                max_memory_restart: '500M',
                env: {
                    NODE_ENV: 'production',
                    EXECUTOR_ID: 'message_hub_daemon',
                    WS_URL: 'ws://localhost:3123/api/ws?type=openclaw',
                    WEBHOOK_URL: 'http://localhost:3123/api/openclaw/webhook',
                    LOG_FILE: path.join(this.logDir, 'message-hub.log')
                },
                error_file: path.join(this.logDir, 'error.log'),
                out_file: path.join(this.logDir, 'out.log'),
                log_file: path.join(this.logDir, 'combined.log'),
                time: true,
                restart_delay: 3000, // 重启延迟 3 秒
                max_restarts: 10, // 最大重启次数
                min_uptime: '10s' // 最小运行时间
            }]
        };
        
        fs.writeFileSync(this.configPath, `module.exports = ${JSON.stringify(config, null, 2)};`);
        console.log(`📁 创建 pm2 配置文件: ${this.configPath}`);
    }
}

// 命令行接口
async function main() {
    const daemon = new MessageHubDaemon();
    const command = process.argv[2];
    
    try {
        switch (command) {
            case 'start':
                await daemon.start();
                break;
            case 'stop':
                await daemon.stop();
                break;
            case 'status':
                await daemon.status();
                break;
            case 'restart':
                await daemon.stop();
                await new Promise(resolve => setTimeout(resolve, 2000));
                await daemon.start();
                break;
            default:
                console.log('📖 使用方法:');
                console.log('  node daemon.js start    # 启动守护进程');
                console.log('  node daemon.js stop     # 停止守护进程');
                console.log('  node daemon.js status   # 查看状态');
                console.log('  node daemon.js restart  # 重启守护进程');
                console.log('\n📝 注意: 首次运行会自动安装 pm2');
                break;
        }
    } catch (err) {
        console.error('❌ 错误:', err.message);
        process.exit(1);
    }
}

if (require.main === module) {
    main();
}

module.exports = MessageHubDaemon;
