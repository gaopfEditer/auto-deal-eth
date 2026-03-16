/**
 * Message Hub 客户端测试脚本
 * 测试 WebSocket 连接和 Webhook 功能
 */

const WebSocket = require('ws');
const http = require('http');
const fs = require('fs');
const path = require('path');

const PORT = parseInt(process.env.PORT || '3123', 10);
const WS_URL = `ws://localhost:${PORT}/api/ws?type=openclaw`;
const WEBHOOK_URL = `/api/openclaw/webhook`;
const LOG_FILE = path.join(__dirname, 'test.log');

class TestLogger {
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
            console.error(`[TestLogger] 无法创建日志文件: ${err.message}`);
        }
    }

    log(level, message, data = null) {
        const timestamp = new Date().toISOString();
        const logEntry = `[${timestamp}] [${level}] ${message}` + (data ? ` ${JSON.stringify(data)}` : '');
        
        console.log(logEntry);
        
        try {
            fs.appendFileSync(this.logFile, logEntry + '\n', 'utf8');
        } catch (err) {
            console.error(`[TestLogger] 写入日志失败: ${err.message}`);
        }
    }

    info(message, data = null) {
        this.log('INFO', message, data);
    }

    error(message, data = null) {
        this.log('ERROR', message, data);
    }
}

function callWebhook(nextRole) {
    return new Promise((resolve, reject) => {
        const body = JSON.stringify({ nextRole });
        const logger = new TestLogger(LOG_FILE);
        
        logger.info(`调用 Webhook: ${nextRole}`);

        const req = http.request({
            hostname: 'localhost',
            port: PORT,
            path: WEBHOOK_URL,
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Content-Length': Buffer.byteLength(body, 'utf8'),
            },
            timeout: 5000,
        }, (res) => {
            let data = '';
            res.on('data', (chunk) => (data += chunk));
            res.on('end', () => {
                try {
                    const result = {
                        statusCode: res.statusCode,
                        body: data ? JSON.parse(data) : null
                    };
                    logger.info(`Webhook 响应: ${res.statusCode}`, result.body);
                    resolve(result);
                } catch (e) {
                    const result = {
                        statusCode: res.statusCode,
                        body: data
                    };
                    logger.info(`Webhook 响应: ${res.statusCode}`, { raw: data });
                    resolve(result);
                }
            });
        });

        req.on('error', (err) => {
            logger.error(`Webhook 请求错误: ${err.message}`);
            reject(err);
        });

        req.on('timeout', () => {
            req.destroy();
            logger.error('Webhook 请求超时');
            reject(new Error('Webhook request timeout'));
        });

        req.write(body);
        req.end();
    });
}

function runTest() {
    return new Promise((resolve, reject) => {
        const logger = new TestLogger(LOG_FILE);
        logger.info('开始 Message Hub 客户端测试');
        logger.info(`端口: ${PORT}`);
        logger.info(`WebSocket URL: ${WS_URL}`);

        console.log('\n> 连接 WebSocket:', WS_URL);
        const ws = new WebSocket(WS_URL);

        const timeout = setTimeout(() => {
            if (!receivedNextRole) {
                ws.close();
                logger.error('测试超时：未在 5 秒内收到 openclaw_next_role');
                reject(new Error('超时：未在 5 秒内收到 openclaw_next_role'));
            }
        }, 5000);

        let receivedWelcome = false;
        let receivedNextRole = false;
        const receivedRoles = [];

        ws.on('open', () => {
            logger.info('WebSocket 已连接');
            console.log('> WebSocket 已连接');
        });

        ws.on('message', (raw) => {
            try {
                const msg = JSON.parse(raw.toString());
                logger.info(`收到 WebSocket 消息: ${msg.type}`, msg);

                if (msg.type === 'welcome') {
                    receivedWelcome = true;
                    logger.info(`收到 welcome, clientId: ${msg.clientId}`);
                    console.log('> 收到 welcome, clientId:', msg.clientId);

                    // 收到 welcome 后调用 webhook
                    setTimeout(() => {
                        console.log('> 调用 OpenClaw Webhook, nextRole: TestRole_1');
                        logger.info('调用 OpenClaw Webhook, nextRole: TestRole_1');
                        
                        callWebhook('TestRole_1')
                            .then((result) => {
                                logger.info(`Webhook 响应结果`, result);
                                console.log('> Webhook 响应:', result.statusCode, JSON.stringify(result.body, null, 2));
                                
                                if (result.statusCode !== 200) {
                                    clearTimeout(timeout);
                                    ws.close();
                                    logger.error(`Webhook 返回 ${result.statusCode}`);
                                    reject(new Error(`Webhook 返回 ${result.statusCode}`));
                                }
                            })
                            .catch((err) => {
                                clearTimeout(timeout);
                                ws.close();
                                logger.error(`Webhook 调用失败: ${err.message}`);
                                reject(err);
                            });
                    }, 200);
                }

                if (msg.type === 'openclaw_next_role') {
                    receivedNextRole = true;
                    receivedRoles.push(msg.nextRole);
                    logger.info(`收到 openclaw_next_role: ${msg.nextRole}`);
                    console.log('> 收到 openclaw_next_role:', msg.nextRole);
                    
                    clearTimeout(timeout);
                    ws.close();
                    logger.info('测试完成，收到的 nextRole 序列:', receivedRoles);
                    resolve(receivedRoles);
                }
            } catch (e) {
                logger.warn(`解析消息失败: ${e.message}`, { raw: raw.toString().slice(0, 80) });
                console.log('> 收到原始消息:', raw.toString().slice(0, 80));
            }
        });

        ws.on('error', (err) => {
            clearTimeout(timeout);
            logger.error(`WebSocket 错误: ${err.message}`);
            reject(err);
        });

        ws.on('close', () => {
            clearTimeout(timeout);
            if (!receivedNextRole) {
                logger.error('WebSocket 已关闭，未收到 openclaw_next_role');
                reject(new Error('WebSocket 已关闭，未收到 openclaw_next_role'));
            }
        });
    });
}

// 运行测试
console.log('Message Hub 客户端测试 (WebSocket + Webhook)');
console.log('端口:', PORT);
console.log('');

const logger = new TestLogger(LOG_FILE);

runTest()
    .then((roles) => {
        console.log('');
        console.log('✅ 测试通过，收到的 nextRole 序列:', roles);
        logger.info('✅ 测试通过，收到的 nextRole 序列:', roles);
        process.exit(0);
    })
    .catch((err) => {
        console.error('');
        console.error('❌ 测试失败:', err.message);
        logger.error('❌ 测试失败:', { error: err.message });
        process.exit(1);
    });
