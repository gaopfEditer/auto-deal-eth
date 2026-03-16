/**
 * OpenClaw 专用执行器
 * 专为 OpenClaw 环境设计的消息中心客户端
 * 
 * 功能：
 * 1. 连接到外部消息中心
 * 2. 接收 openclaw_next_role 任务
 * 3. 调用 OpenClaw 工具处理任务
 * 4. 返回结果到 Webhook
 */

const WebSocket = require('ws');
const axios = require('axios');
const fs = require('fs');
const path = require('path');

// 配置
const EXECUTOR_ID = process.env.EXECUTOR_ID || 'openclaw_executor';
const WS_URL = process.env.WS_URL || 'ws://localhost:3123/api/ws?type=openclaw';
const WEBHOOK_URL = process.env.WEBHOOK_URL || 'http://localhost:3123/api/openclaw/webhook';
const LOG_FILE = process.env.LOG_FILE || path.join(__dirname, 'openclaw-executor.log');

class Logger {
    constructor(logFile) {
        this.logFile = logFile;
        this.ensureLogFile();
    }

    ensureLogFile() {
        try {
            if (!fs.existsSync(this.logFile)) {
                fs.writeFileSync(this.logFile, '');
            }
        } catch (err) {
            console.error(`[Logger] 无法创建日志文件: ${err.message}`);
        }
    }

    log(level, message, data = null) {
        const timestamp = new Date().toISOString();
        const logEntry = `[${timestamp}] [${level}] ${message}` + (data ? ` ${JSON.stringify(data)}` : '');
        
        console.log(logEntry);
        
        try {
            fs.appendFileSync(this.logFile, logEntry + '\n', 'utf8');
        } catch (err) {
            console.error(`[Logger] 写入日志失败: ${err.message}`);
        }
    }

    info(message, data = null) {
        this.log('INFO', message, data);
    }

    error(message, data = null) {
        this.log('ERROR', message, data);
    }

    warn(message, data = null) {
        this.log('WARN', message, data);
    }
}

class OpenClawExecutor {
    constructor() {
        this.logger = new Logger(LOG_FILE);
        this.ws = null;
        this.clientId = null;
        this.isBusy = false;
        this.currentTask = null;
        this.heartbeatInterval = null;
        this.reconnectInterval = null;
        this.reconnectAttempts = 0;
        this.maxReconnectAttempts = 10;
        this.reconnectDelay = 5000; // 5秒
        this.isConnecting = false;
        this.isShuttingDown = false;
        
        // 设备信息
        this.deviceInfo = this.getDeviceInfo();
        
        // OpenClaw 工具映射
        this.toolHandlers = {
            'web_search': this.handleWebSearch.bind(this),
            'exec': this.handleExec.bind(this),
            'browser': this.handleBrowser.bind(this),
            'message': this.handleMessage.bind(this),
            'custom': this.handleCustom.bind(this)
        };
        
        // 绑定方法
        this.handleClose = this.handleClose.bind(this);
        this.handleError = this.handleError.bind(this);
        this.handleOpen = this.handleOpen.bind(this);
        this.handleMessage = this.handleMessage.bind(this);
    }
    
    getDeviceInfo() {
        return {
            executor_id: EXECUTOR_ID,
            platform: process.platform,
            arch: process.arch,
            node_version: process.version,
            cpus: require('os').cpus().length,
            total_memory: Math.round(require('os').totalmem() / 1024 / 1024) + 'MB',
            free_memory: Math.round(require('os').freemem() / 1024 / 1024) + 'MB',
            uptime: Math.round(process.uptime()) + 's',
            hostname: require('os').hostname(),
            network_interfaces: Object.keys(require('os').networkInterfaces()).length,
            timestamp: new Date().toISOString()
        };
    }

    async connect() {
        if (this.isConnecting || this.isShuttingDown) {
            this.logger.warn('正在连接或关闭中，跳过本次连接');
            return false;
        }
        
        this.isConnecting = true;
        this.logger.info(`连接 OpenClaw WebSocket: ${WS_URL} (尝试 ${this.reconnectAttempts + 1}/${this.maxReconnectAttempts})`);
        
        return new Promise((resolve) => {
            try {
                this.ws = new WebSocket(WS_URL);

                this.ws.on('open', this.handleOpen);
                this.ws.on('message', this.handleMessage);
                this.ws.on('error', this.handleError);
                this.ws.on('close', this.handleClose);

                // 设置连接超时
                setTimeout(() => {
                    if (this.ws && this.ws.readyState === WebSocket.CONNECTING) {
                        this.logger.warn('WebSocket 连接超时');
                        this.ws.close();
                        resolve(false);
                    }
                }, 10000); // 10秒超时

            } catch (err) {
                this.logger.error(`创建 WebSocket 失败: ${err.message}`);
                this.isConnecting = false;
                resolve(false);
            }
        });
    }
    
    handleOpen() {
        this.logger.info('OpenClaw WebSocket 连接成功');
        this.isConnecting = false;
        this.reconnectAttempts = 0; // 重置重连计数
        
        // 上报设备信息
        this.reportDeviceInfo();
        
        // 启动心跳
        this.startHeartbeat();
        
        // 清除重连定时器
        if (this.reconnectInterval) {
            clearInterval(this.reconnectInterval);
            this.reconnectInterval = null;
        }
    }
    
    handleClose() {
        this.logger.info('OpenClaw WebSocket 连接已关闭');
        
        // 清理资源
        if (this.heartbeatInterval) {
            clearInterval(this.heartbeatInterval);
            this.heartbeatInterval = null;
        }
        
        this.ws = null;
        this.isConnecting = false;
        
        // 如果不是主动关闭，尝试重连
        if (!this.isShuttingDown) {
            this.scheduleReconnect();
        }
    }
    
    handleError(err) {
        this.logger.error(`OpenClaw WebSocket 错误: ${err.message}`);
        this.isConnecting = false;
    }
    
    scheduleReconnect() {
        if (this.isShuttingDown || this.reconnectInterval) {
            return;
        }
        
        if (this.reconnectAttempts >= this.maxReconnectAttempts) {
            this.logger.error(`已达到最大重连次数 (${this.maxReconnectAttempts})，停止重连`);
            return;
        }
        
        this.reconnectAttempts++;
        const delay = this.reconnectDelay * Math.min(this.reconnectAttempts, 5); // 指数退避，最多5倍
        
        this.logger.info(`等待 ${delay/1000} 秒后重连 (尝试 ${this.reconnectAttempts}/${this.maxReconnectAttempts})`);
        
        this.reconnectInterval = setTimeout(() => {
            this.reconnectInterval = null;
            this.connect().catch(err => {
                this.logger.error(`重连失败: ${err.message}`);
            });
        }, delay);
    }
    
    reportDeviceInfo() {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            // 格式1: 独立的设备信息消息
            const deviceMessage = {
                type: 'device_info',
                executor_id: EXECUTOR_ID,
                client_id: this.clientId,
                device: this.deviceInfo,
                timestamp: new Date().toISOString()
            };
            this.ws.send(JSON.stringify(deviceMessage));
            this.logger.info('上报设备信息', this.deviceInfo);
            
            // 格式2: 在连接消息中包含设备信息（如果需要）
            const connectMessage = {
                type: 'connect',
                executor_id: EXECUTOR_ID,
                client_id: this.clientId,
                device_info: this.deviceInfo,
                capabilities: ['openclaw_tools', 'web_search', 'exec', 'browser', 'message', 'user_message'],
                timestamp: new Date().toISOString()
            };
            this.ws.send(JSON.stringify(connectMessage));
            this.logger.info('发送连接消息', connectMessage);
        }
    }

    handleMessage(message) {
        try {
            const data = JSON.parse(message);
            this.logger.info(`收到 OpenClaw 消息: ${data.type}`, data);

            if (data.type === 'welcome') {
                this.clientId = data.clientId;
                this.logger.info(`获取到 OpenClaw clientId: ${this.clientId}`);
                this.startHeartbeat();
            } else if (data.type === 'openclaw_next_role') {
                this.processOpenClawTask(data.nextRole, data.payload || {});
            } else if (data.type === 'openclaw_command') {
                this.processOpenClawCommand(data);
            } else if (data.type === 'user_message') {
                // 用户消息，原样内容作为对话内容执行
                this.processUserMessage(data);
            }
        } catch (e) {
            this.logger.warn(`解析 OpenClaw 消息失败: ${e.message}`, { raw: message.slice(0, 100) });
        }
    }

    startHeartbeat() {
        // 清理旧的心跳定时器
        if (this.heartbeatInterval) {
            clearInterval(this.heartbeatInterval);
            this.heartbeatInterval = null;
        }
        
        // 每30秒发送一次心跳
        this.heartbeatInterval = setInterval(() => {
            this.sendHeartbeat();
        }, 30000);
        
        // 立即发送第一个心跳
        setTimeout(() => {
            this.sendHeartbeat();
        }, 1000);
    }
    
    sendHeartbeat() {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            const heartbeat = {
                type: 'heartbeat',
                executor_id: EXECUTOR_ID,
                client_id: this.clientId,
                timestamp: new Date().toISOString(),
                status: this.isBusy ? 'BUSY' : 'IDLE',
                current_task: this.currentTask
            };
            
            try {
                this.ws.send(JSON.stringify(heartbeat));
                this.logger.debug('发送 OpenClaw 心跳');
            } catch (err) {
                this.logger.error(`发送心跳失败: ${err.message}`);
            }
        } else {
            this.logger.warn('WebSocket 未连接，跳过心跳');
        }
    }

    async processOpenClawTask(nextRole, payload) {
        if (this.isBusy) {
            this.logger.warn(`OpenClaw 执行器忙，当前任务: ${this.currentTask}`);
            this.sendStatus('BUSY');
            return;
        }

        this.isBusy = true;
        this.currentTask = nextRole;
        this.logger.info(`开始处理 OpenClaw 任务: ${nextRole}`, payload);
        this.sendStatus('RUNNING');

        try {
            // 解析任务类型
            const taskType = payload.action || 'custom';
            const handler = this.toolHandlers[taskType] || this.toolHandlers.custom;
            
            // 执行任务
            const result = await handler(payload);
            
            // 发送结果
            const webhookResult = {
                status: 'completed',
                nextRole: nextRole,
                executor: EXECUTOR_ID,
                task_type: taskType,
                result: result,
                timestamp: new Date().toISOString()
            };

            await this.sendWebhook(webhookResult);
            this.logger.info(`OpenClaw 任务完成: ${nextRole}`);
            
        } catch (err) {
            this.logger.error(`OpenClaw 任务处理失败: ${err.message}`);
            
            const errorResult = {
                status: 'failed',
                nextRole: nextRole,
                executor: EXECUTOR_ID,
                error: err.message,
                timestamp: new Date().toISOString()
            };

            await this.sendWebhook(errorResult);
        } finally {
            this.isBusy = false;
            this.currentTask = null;
            this.sendStatus('IDLE');
        }
    }

    async processOpenClawCommand(commandData) {
        this.logger.info(`处理 OpenClaw 命令: ${commandData.command}`, commandData);
        // 这里可以实现 OpenClaw 命令处理逻辑
    }
    
    async processUserMessage(messageData) {
        if (this.isBusy) {
            this.logger.warn(`OpenClaw 执行器忙，当前任务: ${this.currentTask}`);
            this.sendStatus('BUSY');
            return;
        }

        this.isBusy = true;
        this.currentTask = `user_message_${Date.now()}`;
        this.logger.info(`开始处理用户消息`, messageData);
        this.sendStatus('RUNNING');

        try {
            // 提取用户消息内容
            const userContent = messageData.content || messageData.message || messageData.text || '';
            const messageId = messageData.message_id || messageData.id || this.currentTask;
            
            this.logger.info(`用户消息内容: ${userContent.substring(0, 200)}...`);
            
            // 这里可以调用 OpenClaw 工具处理用户消息
            // 例如：分析消息内容，调用相应的工具
            
            let response = '';
            if (userContent.toLowerCase().includes('搜索')) {
                // 调用 web_search
                response = `将为您搜索: ${userContent}`;
            } else if (userContent.toLowerCase().includes('执行') || userContent.toLowerCase().includes('运行')) {
                // 调用 exec
                response = `将执行命令: ${userContent}`;
            } else {
                // 默认响应
                response = `已收到您的消息: "${userContent.substring(0, 100)}..."`;
            }
            
            const result = {
                type: 'user_message_response',
                message_id: messageId,
                executor_id: EXECUTOR_ID,
                client_id: this.clientId,
                status: 'processed',
                response: response,
                original_content: userContent,
                timestamp: new Date().toISOString()
            };

            // 发送响应到 WebSocket
            if (this.ws && this.ws.readyState === WebSocket.OPEN) {
                this.ws.send(JSON.stringify(result));
                this.logger.info(`用户消息响应已发送`);
            }
            
            // 同时发送到 Webhook
            const webhookResult = {
                type: 'user_message_processed',
                message_id: messageId,
                executor: EXECUTOR_ID,
                status: 'completed',
                result: response,
                original_content: userContent,
                timestamp: new Date().toISOString()
            };
            
            await this.sendWebhook(webhookResult);
            this.logger.info(`用户消息处理完成`);
            
        } catch (err) {
            this.logger.error(`用户消息处理失败: ${err.message}`);
            
            // 发送错误响应
            if (this.ws && this.ws.readyState === WebSocket.OPEN) {
                const errorResult = {
                    type: 'user_message_error',
                    executor_id: EXECUTOR_ID,
                    client_id: this.clientId,
                    status: 'error',
                    error: err.message,
                    timestamp: new Date().toISOString()
                };
                this.ws.send(JSON.stringify(errorResult));
            }
            
            const errorWebhook = {
                type: 'user_message_error',
                message_id: messageData.message_id || this.currentTask,
                executor: EXECUTOR_ID,
                status: 'failed',
                error: err.message,
                timestamp: new Date().toISOString()
            };
            
            await this.sendWebhook(errorWebhook);
        } finally {
            this.isBusy = false;
            this.currentTask = null;
            this.sendStatus('IDLE');
        }
    }

    sendStatus(state) {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            const status = {
                type: 'status',
                executor_id: EXECUTOR_ID,
                state: state,
                current_task: this.currentTask,
                timestamp: new Date().toISOString()
            };
            this.ws.send(JSON.stringify(status));
            this.logger.debug(`发送状态: ${state}`);
        }
    }

    // OpenClaw 工具处理器
    async handleWebSearch(params) {
        this.logger.info(`执行 Web 搜索: ${params.query}`);
        // 这里可以调用 OpenClaw 的 web_search 工具
        return {
            action: 'web_search',
            query: params.query,
            results: `Web search results for: ${params.query}`
        };
    }

    async handleExec(params) {
        this.logger.info(`执行命令: ${params.command}`);
        // 这里可以调用 OpenClaw 的 exec 工具
        return {
            action: 'exec',
            command: params.command,
            result: `Command executed: ${params.command}`
        };
    }

    async handleBrowser(params) {
        this.logger.info(`浏览器操作: ${params.action} ${params.url}`);
        // 这里可以调用 OpenClaw 的 browser 工具
        return {
            action: 'browser',
            url: params.url,
            result: `Browser action: ${params.action}`
        };
    }

    async handleMessage(params) {
        this.logger.info(`发送消息: ${params.to}`, params);
        // 这里可以调用 OpenClaw 的 message 工具
        return {
            action: 'message',
            to: params.to,
            result: `Message sent to: ${params.to}`
        };
    }

    async handleCustom(params) {
        this.logger.info(`自定义任务处理`, params);
        // 自定义任务处理逻辑
        return {
            action: 'custom',
            params: params,
            result: `Custom task processed`
        };
    }

    async sendWebhook(data) {
        try {
            this.logger.info(`发送 OpenClaw Webhook: ${WEBHOOK_URL}`, data);
            const response = await axios.post(WEBHOOK_URL, data, {
                timeout: 10000,
                headers: {
                    'Content-Type': 'application/json'
                }
            });
            this.logger.info(`OpenClaw Webhook 响应: ${response.status}`);
            return response.data;
        } catch (err) {
            this.logger.error(`OpenClaw Webhook 发送失败: ${err.message}`);
            throw err;
        }
    }

    async run() {
        this.logger.info(`启动 OpenClaw 执行器: ${EXECUTOR_ID}`, {
            ws_url: WS_URL,
            webhook_url: WEBHOOK_URL,
            log_file: LOG_FILE
        });

        try {
            await this.connect();
            this.logger.info('OpenClaw 执行器正在运行...');
            
            // 保持进程运行
            process.on('SIGINT', () => {
                this.logger.info('收到 SIGINT 信号，正在关闭 OpenClaw 执行器...');
                if (this.ws) {
                    this.ws.close();
                }
                process.exit(0);
            });

            process.on('SIGTERM', () => {
                this.logger.info('收到 SIGTERM 信号，正在关闭 OpenClaw 执行器...');
                if (this.ws) {
                    this.ws.close();
                }
                process.exit(0);
            });

        } catch (err) {
            this.logger.error(`OpenClaw 执行器启动失败: ${err.message}`);
            process.exit(1);
        }
    }
}

// 启动 OpenClaw 执行器
const executor = new OpenClawExecutor();
executor.run().catch(err => {
    console.error(`OpenClaw 执行器运行失败: ${err.message}`);
    process.exit(1);
});
