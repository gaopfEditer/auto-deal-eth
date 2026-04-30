// 首先备份原始文件
const fs = require('fs');
const path = require('path');
const originalContent = fs.readFileSync(path.join(__dirname, 'openclaw_executor.js'), 'utf8');

// 创建更新后的内容
const updatedContent = originalContent.replace(
`class OpenClawExecutor {
    constructor() {
        this.logger = new Logger(LOG_FILE);
        this.ws = null;
        this.clientId = null;
        this.isBusy = false;
        this.currentTask = null;
        this.heartbeatInterval = null;
        
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
    }`,
`class OpenClawExecutor {
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
    }`
).replace(
`    async connect() {
        this.logger.info(`连接 OpenClaw WebSocket: ${WS_URL}`);
        
        return new Promise((resolve, reject) => {
            this.ws = new WebSocket(WS_URL);

            this.ws.on('open', () => {
                this.logger.info('OpenClaw WebSocket 连接成功');
                // 上报设备信息
                this.reportDeviceInfo();
                resolve(true);
            });

            this.ws.on('message', (data) => {
                this.handleMessage(data.toString());
            });

            this.ws.on('error', (err) => {
                this.logger.error(`OpenClaw WebSocket 错误: ${err.message}`);
                reject(err);
            });

            this.ws.on('close', () => {
                this.logger.info('OpenClaw WebSocket 连接已关闭');
                if (this.heartbeatInterval) {
                    clearInterval(this.heartbeatInterval);
                }
            });
        });
    }`,
`    async connect() {
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
    }`
);

// 写入更新后的文件
fs.writeFileSync(path.join(__dirname, 'openclaw_executor_updated.js'), updatedContent);
console.log('✅ 已创建更新后的 openclaw_executor_updated.js');