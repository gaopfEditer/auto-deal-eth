/**
 * Message Hub 通用执行器客户端
 * 连接到外部消息中心服务
 * 
 * 配置环境变量：
 * - EXECUTOR_ID: 执行器唯一标识
 * - WS_URL: WebSocket 服务器地址 (ws://host:port/api/ws?type=openclaw)
 * - WEBHOOK_URL: Webhook 结果回调地址
 * - LOG_FILE: 日志文件路径 (可选)
 */

const WebSocket = require('ws');
const axios = require('axios');
const fs = require('fs');
const path = require('path');

// 配置
const EXECUTOR_ID = process.env.EXECUTOR_ID || 'executor_js';
const WS_URL = process.env.WS_URL || 'ws://localhost:3123/api/ws?type=openclaw';
const WEBHOOK_URL = process.env.WEBHOOK_URL || 'http://localhost:3123/api/openclaw/webhook';
const LOG_FILE = process.env.LOG_FILE || path.join(__dirname, 'message-hub-client.log');

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
        // 使用北京时间（Asia/Shanghai）作为日志时间
        const timestamp = new Date().toLocaleString('zh-CN', {
            timeZone: 'Asia/Shanghai',
            hour12: false
        });
        const logEntry = `[${timestamp}] [${level}] ${message}` + (data ? ` ${JSON.stringify(data)}` : '');
        
        // 控制台输出
        console.log(logEntry);
        
        // 文件输出
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

    debug(message, data = null) {
        this.log('DEBUG', message, data);
    }
}

class Executor {
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
        this.logger.info(`连接 WebSocket: ${WS_URL} (尝试 ${this.reconnectAttempts + 1}/${this.maxReconnectAttempts})`);
        
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
        this.logger.info('WebSocket 连接成功');
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
        this.logger.info('WebSocket 连接已关闭');
        
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
        this.logger.error(`WebSocket 错误: ${err.message}`);
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
                capabilities: ['web_search', 'exec', 'message', 'user_message'],
                timestamp: new Date().toISOString()
            };
            this.ws.send(JSON.stringify(connectMessage));
            this.logger.info('发送连接消息', connectMessage);
        }
    }

    handleMessage(message) {
        try {
            const data = JSON.parse(message);
            this.logger.info(`收到消息: ${data.type}`, data);

            if (data.type === 'welcome') {
                this.clientId = data.clientId;
                this.logger.info(`获取到 clientId: ${this.clientId}`);
                this.startHeartbeat();
            } else if (data.type === 'openclaw_next_role') {
                this.processTask(data.nextRole);
            } else if (data.type === 'task') {
                // 通用任务格式
                this.processGenericTask(data);
            } else if (data.type === 'echo') {
                // 收到 echo 类型的用户消息，直接转发给服务器
                this.forwardUserMessageToServer(data);
            } else if (data.type === 'user_message') {
                // 用户消息，原样内容作为对话内容执行
                this.processUserMessage(data);
            }
        } catch (e) {
            this.logger.warn(`解析消息失败: ${e.message}`, { raw: message.slice(0, 100) });
        }
    }

    /**
     * 将用户相关消息转发给服务器（如 Webhook 后端）
     * 对于 echo 消息，会优先转发其中的 original 字段
     */
    async forwardUserMessageToServer(messageData) {
        try {
            const payload = messageData.original || messageData;
            if (!WEBHOOK_URL) {
                return;
            }
            await axios.post(WEBHOOK_URL, payload, {
                headers: { 'Content-Type': 'application/json' },
                timeout: 10000
            });
        } catch (err) {
            this.logger.warn(`转发用户消息到服务器失败: ${err.message}`);
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
                timestamp: new Date().toISOString()
            };
            
            try {
                this.ws.send(JSON.stringify(heartbeat));
                // 心跳发送结果不再打印日志，避免日志噪音
            } catch (err) {
                // 如果你连错误也不想看，可以把这一行也去掉
                this.logger.error(`发送心跳失败: ${err.message}`);
            }
        } else {
            // WebSocket 未连接时也不打印心跳相关日志
        }
    }

    async processTask(nextRole) {
        if (this.isBusy) {
            this.logger.warn(`执行器忙，当前任务: ${this.currentTask}`);
            return;
        }

        this.isBusy = true;
        this.currentTask = nextRole;
        this.logger.info(`开始处理任务: ${nextRole}`);

        try {
            // 这里可以添加任务处理逻辑
            const result = {
                status: 'completed',
                nextRole: nextRole,
                executor: EXECUTOR_ID,
                result: `Processed ${nextRole}`,
                timestamp: new Date().toISOString()
            };

            await this.sendWebhook(result);
            this.logger.info(`任务完成: ${nextRole}`);
        } catch (err) {
            this.logger.error(`任务处理失败: ${err.message}`);
        } finally {
            this.isBusy = false;
            this.currentTask = null;
        }
    }

    async processGenericTask(taskData) {
        if (this.isBusy) {
            this.logger.warn(`执行器忙，当前任务: ${this.currentTask}`);
            return;
        }

        this.isBusy = true;
        this.currentTask = taskData.task_id;
        this.logger.info(`开始处理通用任务: ${taskData.task_id}`, taskData);

        try {
            // 这里可以添加通用任务处理逻辑
            const result = {
                task_id: taskData.task_id,
                status: 'completed',
                executor: EXECUTOR_ID,
                result: `Processed task ${taskData.task_id}`,
                timestamp: new Date().toISOString()
            };

            await this.sendWebhook(result);
            this.logger.info(`通用任务完成: ${taskData.task_id}`);
        } catch (err) {
            this.logger.error(`通用任务处理失败: ${err.message}`);
        } finally {
            this.isBusy = false;
            this.currentTask = null;
        }
    }
    
    async processUserMessage(messageData) {
        if (this.isBusy) {
            this.logger.warn(`执行器忙，当前任务: ${this.currentTask}`);
            // 发送忙状态响应
            if (this.ws && this.ws.readyState === WebSocket.OPEN) {
                const busyResult = {
                    type: 'user_message_response',
                    message_id: messageData.message_id || `user_message_${Date.now()}`,
                    executor_id: EXECUTOR_ID,
                    client_id: this.clientId,
                    status: 'busy',
                    response: '执行器正忙，请稍后再试',
                    original_content: messageData.content || '',
                    timestamp: new Date().toISOString()
                };
                this.ws.send(JSON.stringify(busyResult));
            }
            return;
        }

        this.isBusy = true;
        this.currentTask = `user_message_${Date.now()}`;
        const messageId = messageData.message_id || messageData.id || this.currentTask;
        const userContent = messageData.content || messageData.message || messageData.text || '';
        
        this.logger.info(`开始处理用户消息: ${userContent.substring(0, 100)}...`);

        try {
            // 1. 先发送接收确认
            const ackResult = {
                type: 'user_message_response',
                message_id: messageId,
                executor_id: EXECUTOR_ID,
                client_id: this.clientId,
                status: 'processing',
                response: `正在处理: "${userContent.substring(0, 50)}..."`,
                original_content: userContent,
                timestamp: new Date().toISOString()
            };
            
            if (this.ws && this.ws.readyState === WebSocket.OPEN) {
                this.ws.send(JSON.stringify(ackResult));
                this.logger.info(`已发送处理中确认`);
            }
            
            // 2. 分析用户指令并调用相应的 OpenClaw 工具
            const processingResult = await this.processWithOpenClaw(userContent, messageId);
            
            // 3. 发送处理结果
            const finalResult = {
                type: 'user_message_response',
                message_id: messageId,
                executor_id: EXECUTOR_ID,
                client_id: this.clientId,
                status: 'completed',
                response: processingResult.response,
                result: processingResult.result,
                original_content: userContent,
                timestamp: new Date().toISOString()
            };
            
            if (this.ws && this.ws.readyState === WebSocket.OPEN) {
                this.ws.send(JSON.stringify(finalResult));
                this.logger.info(`用户消息处理完成，结果已发送`);
            }
            
            // 4. 尝试发送 Webhook（可选）
            try {
                const webhookResult = {
                    type: 'user_message_processed',
                    message_id: messageId,
                    executor: EXECUTOR_ID,
                    status: 'completed',
                    result: processingResult.response,
                    original_content: userContent,
                    timestamp: new Date().toISOString()
                };
                
                await this.sendWebhook(webhookResult);
                this.logger.info(`Webhook 发送成功`);
            } catch (webhookErr) {
                this.logger.warn(`Webhook 发送失败（不影响主流程）: ${webhookErr.message}`);
            }
            
        } catch (err) {
            this.logger.error(`用户消息处理失败: ${err.message}`);
            
            // 发送错误响应
            if (this.ws && this.ws.readyState === WebSocket.OPEN) {
                const errorResult = {
                    type: 'user_message_response',
                    message_id: messageId,
                    executor_id: EXECUTOR_ID,
                    client_id: this.clientId,
                    status: 'error',
                    response: `处理失败: ${err.message}`,
                    original_content: userContent,
                    timestamp: new Date().toISOString()
                };
                this.ws.send(JSON.stringify(errorResult));
            }
        } finally {
            this.isBusy = false;
            this.currentTask = null;
        }
    }
    
    async processWithOpenClaw(userContent, messageId) {
        this.logger.info(`使用 OpenClaw 处理消息: ${userContent.substring(0, 100)}...`);
        
        // 分析用户指令，决定调用哪个工具
        const command = this.analyzeCommand(userContent);
        
        switch (command.type) {
            case 'disk_space':
                return await this.handleDiskSpace();
                
            case 'system_info':
                return await this.handleSystemInfo();
                
            case 'exec_command':
                return await this.handleExecCommand(command.parameters);
                
            case 'web_search':
                return await this.handleWebSearch(command.parameters);
                
            case 'unknown':
            default:
                // 默认走 OpenClaw 接口，让大模型处理自然语言
                try {
                    const apiUrl = 'http://127.0.0.1:18789/v1/chat/completions';
                    const payload = {
                        model: 'openclaw',
                        messages: [
                            {
                                role: 'user',
                                content: userContent
                            }
                        ]
                    };

                    const headers = {
                        'Authorization': `Bearer ${process.env.OPENCLAW_API_TOKEN || '7d18c652bc2282d424bb4071f6ec3daec4c7b7f2781d8bb5'}`,
                        'Content-Type': 'application/json',
                        'Accept': 'application/json',
                        'x-openclaw-agent-id': 'agent:main:cron:d99f802b-dcc9-4ece-8bc5-3b794677dd38'
                    };
                    
                    this.logger.info(`调用 OpenClaw 接口xx: ${JSON.stringify(payload)}, ${JSON.stringify(headers)}, `);

                    const resp = await axios.post(apiUrl, payload, { headers, timeout: 30000 });
                    const choice = resp.data && resp.data.choices && resp.data.choices[0];
                    const content = choice && choice.message && choice.message.content
                        ? choice.message.content
                        : '（接口返回格式异常，未获取到内容）';

                    return {
                        response: content,
                        result: {
                            type: 'openclaw_completion',
                            raw: resp.data
                        }
                    };
                } catch (err) {
                    this.logger.error(`7777777 调用 OpenClaw 接口失败: ${err.message}`);
                    return {
                        response: `已收到您的消息，但调用 OpenClaw 接口失败，改为简单确认: "${userContent.substring(0, 50)}..."`,
                        result: {
                            type: 'acknowledged_fallback',
                            error: err.message,
                            content: userContent
                        }
                    };
                }
        }
    }
    
    analyzeCommand(userContent) {
        const content = userContent.toLowerCase();
        
        // 检查磁盘空间相关
        if (content.includes('硬盘') || content.includes('磁盘') || content.includes('剩余') || 
            content.includes('空间') || content.includes('disk') || content.includes('space')) {
            return { type: 'disk_space' };
        }
        
        // 检查系统信息相关
        if (content.includes('系统') || content.includes('信息') || content.includes('设备') || 
            content.includes('system') || content.includes('info')) {
            return { type: 'system_info' };
        }
        
        // 检查执行命令
        if (content.includes('执行') || content.includes('运行') || content.includes('命令') || 
            content.includes('exec') || content.includes('run') || content.includes('cmd')) {
            // 提取命令内容
            const match = userContent.match(/执行\s+(.+)|运行\s+(.+)|命令\s+(.+)/i);
            if (match) {
                const cmd = match[1] || match[2] || match[3];
                return { type: 'exec_command', parameters: { command: cmd } };
            }
        }
        
        // 检查搜索
        if (content.includes('搜索') || content.includes('查找') || content.includes('search')) {
            const match = userContent.match(/搜索\s+(.+)|查找\s+(.+)/i);
            if (match) {
                const query = match[1] || match[2];
                return { type: 'web_search', parameters: { query } };
            }
        }
        
        return { type: 'unknown' };
    }
    
    async handleDiskSpace() {
        this.logger.info('处理磁盘空间查询');
        
        try {
            // 使用 exec 工具获取磁盘信息
            const { exec } = require('child_process');
            
            return new Promise((resolve) => {
                exec('wmic logicaldisk get size,freespace,caption', (error, stdout, stderr) => {
                    if (error) {
                        this.logger.error(`获取磁盘信息失败: ${error.message}`);
                        resolve({
                            response: '获取磁盘信息失败',
                            result: { error: error.message }
                        });
                        return;
                    }
                    
                    // 解析输出
                    const lines = stdout.split('\n').filter(line => line.trim());
                    let diskInfo = [];
                    
                    for (let i = 1; i < lines.length; i++) { // 跳过标题行
                        const parts = lines[i].trim().split(/\s+/);
                        if (parts.length >= 3) {
                            const drive = parts[0];
                            const free = parseInt(parts[1]) || 0;
                            const total = parseInt(parts[2]) || 0;
                            const used = total - free;
                            const percent = total > 0 ? Math.round((used / total) * 100) : 0;
                            
                            diskInfo.push({
                                drive,
                                free: Math.round(free / 1024 / 1024 / 1024 * 100) / 100 + 'GB',
                                total: Math.round(total / 1024 / 1024 / 1024 * 100) / 100 + 'GB',
                                used: Math.round(used / 1024 / 1024 / 1024 * 100) / 100 + 'GB',
                                percent: percent + '%'
                            });
                        }
                    }
                    
                    const response = `磁盘空间信息:\n${diskInfo.map(d => 
                        `${d.drive}: 总共 ${d.total}, 可用 ${d.free}, 使用率 ${d.percent}`
                    ).join('\n')}`;
                    
                    resolve({
                        response: response,
                        result: { disks: diskInfo }
                    });
                });
            });
            
        } catch (err) {
            this.logger.error(`处理磁盘空间失败: ${err.message}`);
            return {
                response: '处理磁盘空间查询时出错',
                result: { error: err.message }
            };
        }
    }
    
    async handleSystemInfo() {
        this.logger.info('处理系统信息查询');
        
        try {
            const os = require('os');
            
            const info = {
                platform: os.platform(),
                arch: os.arch(),
                cpus: os.cpus().length,
                totalMemory: Math.round(os.totalmem() / 1024 / 1024 / 1024 * 100) / 100 + 'GB',
                freeMemory: Math.round(os.freemem() / 1024 / 1024 / 1024 * 100) / 100 + 'GB',
                uptime: Math.round(os.uptime() / 3600 * 100) / 100 + '小时',
                hostname: os.hostname(),
                nodeVersion: process.version
            };
            
            const response = `系统信息:
• 平台: ${info.platform} (${info.arch})
• CPU核心: ${info.cpus}
• 内存: 总共 ${info.totalMemory}, 可用 ${info.freeMemory}
• 运行时间: ${info.uptime}
• 主机名: ${info.hostname}
• Node版本: ${info.nodeVersion}`;
            
            return {
                response: response,
                result: info
            };
            
        } catch (err) {
            this.logger.error(`处理系统信息失败: ${err.message}`);
            return {
                response: '处理系统信息查询时出错',
                result: { error: err.message }
            };
        }
    }
    
    async handleExecCommand(parameters) {
        this.logger.info(`执行命令: ${parameters.command}`);
        
        try {
            const { exec } = require('child_process');
            
            return new Promise((resolve) => {
                exec(parameters.command, { timeout: 30000 }, (error, stdout, stderr) => {
                    if (error) {
                        this.logger.error(`命令执行失败: ${error.message}`);
                        resolve({
                            response: `命令执行失败: ${error.message}`,
                            result: { error: error.message, stderr }
                        });
                        return;
                    }
                    
                    const output = stdout || stderr || '(无输出)';
                    const truncated = output.length > 500 ? output.substring(0, 500) + '...' : output;
                    
                    resolve({
                        response: `命令执行完成:\n${truncated}`,
                        result: { stdout, stderr, exitCode: error ? error.code : 0 }
                    });
                });
            });
            
        } catch (err) {
            this.logger.error(`执行命令失败: ${err.message}`);
            return {
                response: `执行命令时出错: ${err.message}`,
                result: { error: err.message }
            };
        }
    }
    
    async handleWebSearch(parameters) {
        this.logger.info(`执行搜索: ${parameters.query}`);
        
        try {
            // 这里可以集成 OpenClaw 的 web_search 工具
            // 暂时返回模拟结果
            return {
                response: `搜索 "${parameters.query}" 的结果:\n1. 相关结果 1\n2. 相关结果 2\n3. 相关结果 3`,
                result: { 
                    query: parameters.query,
                    results: [
                        { title: '相关结果 1', url: '#' },
                        { title: '相关结果 2', url: '#' },
                        { title: '相关结果 3', url: '#' }
                    ]
                }
            };
            
        } catch (err) {
            this.logger.error(`搜索失败: ${err.message}`);
            return {
                response: `搜索时出错: ${err.message}`,
                result: { error: err.message }
            };
        }
    }

    async sendWebhook(data) {
        try {
            this.logger.info(`发送 Webhook: ${WEBHOOK_URL}`, data);
            const response = await axios.post(WEBHOOK_URL, data, {
                timeout: 10000,
                headers: {
                    'Content-Type': 'application/json'
                }
            });
            this.logger.info(`Webhook 响应: ${response.status}`);
            return response.data;
        } catch (err) {
            this.logger.error(`Webhook 发送失败: ${err.message}`);
            throw err;
        }
    }

    async run() {
        this.logger.info(`启动执行器: ${EXECUTOR_ID}`, {
            ws_url: WS_URL,
            webhook_url: WEBHOOK_URL,
            log_file: LOG_FILE
        });

        try {
            const connected = await this.connect();
            if (!connected) {
                this.logger.warn('首次连接失败，将尝试重连');
            }
            
            this.logger.info('执行器正在运行...');
            
            // 设置信号处理
            this.setupSignalHandlers();
            
            // 保持进程运行
            this.keepAlive();
            
        } catch (err) {
            this.logger.error(`执行器启动失败: ${err.message}`);
            process.exit(1);
        }
    }
    
    setupSignalHandlers() {
        process.on('SIGINT', () => {
            this.logger.info('收到 SIGINT 信号，正在优雅关闭...');
            this.shutdown();
        });
        
        process.on('SIGTERM', () => {
            this.logger.info('收到 SIGTERM 信号，正在优雅关闭...');
            this.shutdown();
        });
        
        process.on('uncaughtException', (err) => {
            this.logger.error(`未捕获的异常: ${err.message}`, { stack: err.stack });
            // 不退出，尝试恢复
        });
        
        process.on('unhandledRejection', (reason, promise) => {
            this.logger.error(`未处理的 Promise 拒绝: ${reason}`);
        });
    }
    
    keepAlive() {
        // 主循环，保持进程运行
        const interval = setInterval(() => {
            if (this.isShuttingDown) {
                clearInterval(interval);
                this.logger.info('保活循环已停止');
            }
        }, 60000); // 每分钟检查一次
        
        this.logger.info('执行器进入保活模式');
    }
    
    shutdown() {
        this.logger.info('开始关闭执行器...');
        this.isShuttingDown = true;
        
        // 清理定时器
        if (this.heartbeatInterval) {
            clearInterval(this.heartbeatInterval);
            this.heartbeatInterval = null;
        }
        
        if (this.reconnectInterval) {
            clearTimeout(this.reconnectInterval);
            this.reconnectInterval = null;
        }
        
        // 关闭 WebSocket
        if (this.ws) {
            this.ws.close();
            this.ws = null;
        }
        
        this.logger.info('执行器已关闭');
        
        // 延迟退出，确保日志写入完成
        setTimeout(() => {
            process.exit(0);
        }, 1000);
    }
}

// 启动执行器
const executor = new Executor();
executor.run().catch(err => {
    console.error(`执行器运行失败: ${err.message}`);
    process.exit(1);
});
