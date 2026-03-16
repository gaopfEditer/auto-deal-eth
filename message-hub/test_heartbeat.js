/**
 * 测试心跳保活和自动重连功能
 */

const WebSocket = require('ws');

// 模拟一个简单的服务器来测试重连
class TestServer {
    constructor(port = 9999) {
        this.port = port;
        this.server = null;
        this.connections = [];
        this.heartbeatCount = 0;
    }
    
    start() {
        return new Promise((resolve) => {
            this.server = new WebSocket.Server({ port: this.port });
            
            this.server.on('listening', () => {
                console.log(`✅ 测试服务器启动在端口 ${this.port}`);
                resolve();
            });
            
            this.server.on('connection', (ws) => {
                console.log('📡 客户端连接');
                this.connections.push(ws);
                
                // 发送欢迎消息
                const welcomeMsg = {
                    type: 'welcome',
                    clientId: 'test_client_' + Date.now(),
                    message: '测试服务器欢迎您',
                    timestamp: new Date().toISOString()
                };
                ws.send(JSON.stringify(welcomeMsg));
                
                ws.on('message', (data) => {
                    try {
                        const msg = JSON.parse(data.toString());
                        
                        if (msg.type === 'heartbeat') {
                            this.heartbeatCount++;
                            console.log(`💓 收到心跳 #${this.heartbeatCount}`);
                            
                            // 发送回显
                            const echoMsg = {
                                type: 'echo',
                                original: msg,
                                message: '心跳已接收',
                                timestamp: new Date().toISOString()
                            };
                            ws.send(JSON.stringify(echoMsg));
                        }
                        
                        if (msg.type === 'device_info') {
                            console.log(`📱 收到设备信息: ${msg.executor_id}`);
                        }
                        
                    } catch (e) {
                        console.log('收到消息:', data.toString().slice(0, 100));
                    }
                });
                
                ws.on('close', () => {
                    console.log('❌ 客户端断开连接');
                    this.connections = this.connections.filter(conn => conn !== ws);
                });
            });
        });
    }
    
    // 模拟服务器关闭
    disconnectAll() {
        console.log('🛑 断开所有客户端连接');
        this.connections.forEach(ws => {
            ws.close();
        });
        this.connections = [];
    }
    
    stop() {
        return new Promise((resolve) => {
            if (this.server) {
                this.server.close(() => {
                    console.log('🛑 测试服务器已停止');
                    resolve();
                });
            } else {
                resolve();
            }
        });
    }
}

// 测试执行器
async function testHeartbeatAndReconnect() {
    console.log('🧪 测试心跳保活和自动重连功能');
    console.log('='.repeat(50));
    
    // 启动测试服务器
    const testServer = new TestServer();
    await testServer.start();
    
    // 修改环境变量，让执行器连接到测试服务器
    process.env.WS_URL = 'ws://localhost:9999';
    process.env.EXECUTOR_ID = 'test_heartbeat';
    process.env.WEBHOOK_URL = 'http://localhost:9999/webhook';
    
    // 动态加载执行器
    const { Executor } = require('./executor.js');
    const executor = new Executor();
    
    console.log('\n1. 启动执行器...');
    await executor.run();
    
    // 等待连接建立
    await new Promise(resolve => setTimeout(resolve, 3000));
    
    console.log('\n2. 验证心跳...');
    console.log(`   心跳计数: ${testServer.heartbeatCount}`);
    
    if (testServer.heartbeatCount > 0) {
        console.log('   ✅ 心跳保活功能正常');
    } else {
        console.log('   ❌ 心跳保活功能异常');
    }
    
    console.log('\n3. 测试自动重连...');
    console.log('   模拟服务器断开连接...');
    testServer.disconnectAll();
    
    // 等待重连
    await new Promise(resolve => setTimeout(resolve, 10000));
    
    console.log(`   重连后心跳计数: ${testServer.heartbeatCount}`);
    
    if (testServer.heartbeatCount > 3) {
        console.log('   ✅ 自动重连功能正常');
    } else {
        console.log('   ❌ 自动重连功能异常');
    }
    
    console.log('\n4. 清理...');
    // 优雅关闭
    executor.shutdown();
    await testServer.stop();
    
    console.log('\n🎉 测试完成!');
}

// 运行测试
testHeartbeatAndReconnect().catch(err => {
    console.error('❌ 测试失败:', err.message);
    process.exit(1);
});
