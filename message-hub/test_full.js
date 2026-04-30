/**
 * 完整的设备信息和用户消息测试
 * 模拟服务端和客户端交互
 */

const WebSocket = require('ws');
const http = require('http');

const PORT = 3123;
const WS_URL = `ws://localhost:${PORT}/api/ws?type=openclaw`;

// 模拟服务端行为
class MockServerSimulator {
    constructor() {
        this.deviceInfoReceived = false;
        this.userMessageProcessed = false;
        this.deviceInfo = null;
        this.userResponse = null;
    }
    
    async runTest() {
        console.log('🚀 开始完整测试...');
        console.log(`连接: ${WS_URL}`);
        
        return new Promise((resolve, reject) => {
            const ws = new WebSocket(WS_URL);
            const timeout = setTimeout(() => {
                ws.close();
                reject(new Error('测试超时'));
            }, 10000);
            
            ws.on('open', () => {
                console.log('✅ 连接到服务端');
            });
            
            ws.on('message', (data) => {
                try {
                    const msg = JSON.parse(data.toString());
                    console.log(`📨 收到消息: ${msg.type}`);
                    
                    // 处理设备信息
                    if (msg.type === 'device_info') {
                        this.deviceInfoReceived = true;
                        this.deviceInfo = msg.device;
                        console.log('✅ 收到设备信息:', {
                            executor_id: msg.executor_id,
                            platform: msg.device?.platform,
                            node_version: msg.device?.node_version
                        });
                        
                        // 发送欢迎消息
                        const welcomeMsg = {
                            type: 'welcome',
                            clientId: `client_${Date.now()}`,
                            message: '欢迎连接，设备信息已接收',
                            timestamp: new Date().toISOString()
                        };
                        ws.send(JSON.stringify(welcomeMsg));
                        console.log('📤 发送欢迎消息');
                        
                        // 等待后发送用户消息
                        setTimeout(() => {
                            const userMsg = {
                                type: 'user_message',
                                message_id: `test_user_${Date.now()}`,
                                content: '测试用户消息：请执行一个命令',
                                user_id: 'test_user',
                                timestamp: new Date().toISOString()
                            };
                            ws.send(JSON.stringify(userMsg));
                            console.log('📤 发送用户消息:', userMsg.content);
                        }, 1000);
                    }
                    
                    // 处理连接消息
                    if (msg.type === 'connect') {
                        console.log('✅ 收到连接消息，能力:', msg.capabilities);
                    }
                    
                    // 处理用户消息响应
                    if (msg.type === 'user_message_response') {
                        this.userMessageProcessed = true;
                        this.userResponse = msg;
                        console.log('✅ 收到用户消息响应:', msg.response);
                        console.log('📝 原始内容:', msg.original_content);
                        
                        // 测试完成
                        clearTimeout(timeout);
                        ws.close();
                        resolve({
                            deviceInfoReceived: this.deviceInfoReceived,
                            userMessageProcessed: this.userMessageProcessed,
                            deviceInfo: this.deviceInfo,
                            userResponse: this.userResponse
                        });
                    }
                    
                    // 处理心跳
                    if (msg.type === 'heartbeat') {
                        console.log('💓 收到心跳');
                    }
                    
                } catch (e) {
                    console.error('解析消息失败:', e.message);
                }
            });
            
            ws.on('error', (err) => {
                clearTimeout(timeout);
                reject(err);
            });
            
            ws.on('close', () => {
                clearTimeout(timeout);
                if (!this.deviceInfoReceived || !this.userMessageProcessed) {
                    reject(new Error(`测试未完成: deviceInfo=${this.deviceInfoReceived}, userMessage=${this.userMessageProcessed}`));
                }
            });
        });
    }
}

// 运行测试
async function runFullTest() {
    const simulator = new MockServerSimulator();
    
    try {
        const result = await simulator.runTest();
        
        console.log('\n📊 测试结果:');
        console.log('='.repeat(50));
        console.log('✅ 设备信息上报:', result.deviceInfoReceived ? '成功' : '失败');
        console.log('✅ 用户消息处理:', result.userMessageProcessed ? '成功' : '失败');
        
        if (result.deviceInfo) {
            console.log('\n📱 设备信息详情:');
            console.log(`  执行器ID: ${result.deviceInfo.executor_id}`);
            console.log(`  平台: ${result.deviceInfo.platform}`);
            console.log(`  CPU核心: ${result.deviceInfo.cpus}`);
            console.log(`  内存: ${result.deviceInfo.total_memory}`);
            console.log(`  Node版本: ${result.deviceInfo.node_version}`);
        }
        
        if (result.userResponse) {
            console.log('\n💬 用户消息响应详情:');
            console.log(`  消息ID: ${result.userResponse.message_id}`);
            console.log(`  状态: ${result.userResponse.status}`);
            console.log(`  响应: ${result.userResponse.response}`);
        }
        
        console.log('\n🎉 完整测试通过!');
        return result;
        
    } catch (err) {
        console.error('\n❌ 测试失败:', err.message);
        throw err;
    }
}

// 主函数
console.log('🔧 Message Hub 完整功能测试');
console.log('='.repeat(50));

runFullTest()
    .then(() => {
        console.log('\n✅ 所有测试完成!');
        process.exit(0);
    })
    .catch((err) => {
        console.error('\n❌ 测试失败:', err.message);
        process.exit(1);
    });
