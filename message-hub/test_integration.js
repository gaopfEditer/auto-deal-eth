/**
 * 直接测试执行器的设备信息上报和用户消息处理功能
 */

const WebSocket = require('ws');

// 模拟一个简单的 WebSocket 服务器来测试执行器
class MockServer {
    constructor(port = 3123) {
        this.port = port;
        this.server = null;
        this.clients = new Map();
        this.messageHistory = [];
    }
    
    start() {
        return new Promise((resolve) => {
            this.server = new WebSocket.Server({ port: this.port });
            
            this.server.on('listening', () => {
                console.log(`✅ Mock服务器启动在端口 ${this.port}`);
                resolve();
            });
            
            this.server.on('connection', (ws, req) => {
                const clientId = `client_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
                this.clients.set(clientId, ws);
                
                console.log(`📡 客户端连接: ${clientId}`);
                
                // 发送欢迎消息
                const welcomeMsg = {
                    type: 'welcome',
                    clientId: clientId,
                    message: '欢迎连接到测试服务器',
                    timestamp: new Date().toISOString()
                };
                ws.send(JSON.stringify(welcomeMsg));
                
                ws.on('message', (data) => {
                    try {
                        const msg = JSON.parse(data.toString());
                        this.messageHistory.push({
                            clientId,
                            type: msg.type,
                            data: msg,
                            timestamp: new Date().toISOString()
                        });
                        
                        console.log(`📨 收到来自 ${clientId} 的消息: ${msg.type}`);
                        
                        // 处理不同类型的消息
                        if (msg.type === 'device_info') {
                            console.log(`📊 设备信息: ${msg.executor_id} - ${msg.device?.platform}`);
                            
                            // 发送确认
                            const echoMsg = {
                                type: 'echo',
                                original: msg,
                                message: '服务器已收到设备信息',
                                timestamp: new Date().toISOString()
                            };
                            ws.send(JSON.stringify(echoMsg));
                            
                            // 模拟发送用户消息
                            setTimeout(() => {
                                const userMsg = {
                                    type: 'user_message',
                                    message_id: 'test_msg_' + Date.now(),
                                    content: '测试用户消息：请帮我搜索信息',
                                    timestamp: new Date().toISOString()
                                };
                                ws.send(JSON.stringify(userMsg));
                                console.log(`📤 发送用户消息到 ${clientId}`);
                            }, 500);
                        }
                        
                        if (msg.type === 'user_message_response') {
                            console.log(`✅ 收到用户消息响应: ${msg.response}`);
                            console.log(`📝 原始内容: ${msg.original_content?.substring(0, 50)}...`);
                        }
                        
                        if (msg.type === 'heartbeat') {
                            const echoMsg = {
                                type: 'echo',
                                original: msg,
                                message: '心跳已接收',
                                timestamp: new Date().toISOString()
                            };
                            ws.send(JSON.stringify(echoMsg));
                        }
                        
                    } catch (e) {
                        console.error(`解析消息失败: ${e.message}`);
                    }
                });
                
                ws.on('close', () => {
                    console.log(`❌ 客户端断开: ${clientId}`);
                    this.clients.delete(clientId);
                });
                
                ws.on('error', (err) => {
                    console.error(`客户端错误 ${clientId}: ${err.message}`);
                });
            });
        });
    }
    
    stop() {
        return new Promise((resolve) => {
            if (this.server) {
                this.server.close(() => {
                    console.log('🛑 Mock服务器已停止');
                    resolve();
                });
            } else {
                resolve();
            }
        });
    }
    
    getMessagesByType(type) {
        return this.messageHistory.filter(msg => msg.type === type);
    }
}

// 测试执行器
async function testExecutor() {
    const mockServer = new MockServer(8765); // 使用不同端口避免冲突
    await mockServer.start();
    
    // 启动执行器（在子进程中）
    const { spawn } = require('child_process');
    const executorProcess = spawn('node', ['executor.js'], {
        cwd: __dirname,
        env: {
            ...process.env,
            EXECUTOR_ID: 'test_executor',
            WS_URL: 'ws://localhost:8765/api/ws?type=openclaw',
            WEBHOOK_URL: 'http://localhost:8765/api/openclaw/webhook'
        }
    });
    
    executorProcess.stdout.on('data', (data) => {
        console.log(`[执行器输出] ${data.toString().trim()}`);
    });
    
    executorProcess.stderr.on('data', (data) => {
        console.error(`[执行器错误] ${data.toString().trim()}`);
    });
    
    // 等待测试完成
    await new Promise(resolve => setTimeout(resolve, 3000));
    
    // 检查结果
    const deviceMessages = mockServer.getMessagesByType('device_info');
    const userResponses = mockServer.getMessagesByType('user_message_response');
    
    console.log('\n📊 测试结果:');
    console.log(`✅ 设备信息上报: ${deviceMessages.length > 0 ? '成功' : '失败'}`);
    console.log(`✅ 用户消息处理: ${userResponses.length > 0 ? '成功' : '失败'}`);
    
    if (deviceMessages.length > 0) {
        console.log(`📱 设备信息详情:`, {
            executor_id: deviceMessages[0].data.executor_id,
            platform: deviceMessages[0].data.device?.platform,
            node_version: deviceMessages[0].data.device?.node_version
        });
    }
    
    if (userResponses.length > 0) {
        console.log(`💬 用户响应详情:`, {
            response: userResponses[0].data.response,
            status: userResponses[0].data.status
        });
    }
    
    // 清理
    executorProcess.kill();
    await mockServer.stop();
    
    return {
        deviceInfoReported: deviceMessages.length > 0,
        userMessageProcessed: userResponses.length > 0,
        deviceMessages,
        userResponses
    };
}

// 运行测试
console.log('🚀 开始测试执行器功能...\n');

testExecutor()
    .then((result) => {
        console.log('\n🎉 测试完成!');
        
        if (result.deviceInfoReported && result.userMessageProcessed) {
            console.log('✅ 所有测试通过!');
            process.exit(0);
        } else {
            console.log('❌ 部分测试失败:');
            console.log(`  设备信息上报: ${result.deviceInfoReported ? '✅' : '❌'}`);
            console.log(`  用户消息处理: ${result.userMessageProcessed ? '✅' : '❌'}`);
            process.exit(1);
        }
    })
    .catch((err) => {
        console.error('\n💥 测试失败:', err.message);
        process.exit(1);
    });
