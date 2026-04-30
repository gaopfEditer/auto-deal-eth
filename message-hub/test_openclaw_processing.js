/**
 * 测试 OpenClaw 指令处理
 * 发送各种指令测试执行器的处理能力
 */

const WebSocket = require('ws');

const WS_URL = 'ws://localhost:3123/api/ws?type=openclaw';

console.log('🧪 测试 OpenClaw 指令处理');
console.log(`连接: ${WS_URL}`);

const ws = new WebSocket(WS_URL);
let testCount = 0;
let passedTests = 0;

ws.on('open', () => {
    console.log('✅ 连接到服务端');
    
    // 等待执行器连接
    setTimeout(() => {
        console.log('\n📤 开始发送测试指令...');
        
        // 测试1: 磁盘空间查询
        setTimeout(() => {
            testCount++;
            console.log(`\n${testCount}. 测试磁盘空间查询...`);
            
            const diskQuery = {
                type: 'user_message',
                openclawPeers: [
                    {
                        id: 'client_1773641570043_94kgysbg0', // 从日志中获取的执行器clientId
                        clientType: 'openclaw',
                        deviceInfo: null
                    }
                ],
                content: '看看设备的硬盘剩余多少空间',
                timestamp: new Date().toISOString()
            };
            
            console.log(`   发送: ${diskQuery.content}`);
            ws.send(JSON.stringify(diskQuery));
            
        }, 1000);
        
        // 测试2: 系统信息查询
        setTimeout(() => {
            testCount++;
            console.log(`\n${testCount}. 测试系统信息查询...`);
            
            const sysQuery = {
                type: 'user_message',
                openclawPeers: [
                    {
                        id: 'client_1773641570043_94kgysbg0',
                        clientType: 'openclaw',
                        deviceInfo: null
                    }
                ],
                content: '查看系统信息',
                timestamp: new Date().toISOString()
            };
            
            console.log(`   发送: ${sysQuery.content}`);
            ws.send(JSON.stringify(sysQuery));
            
        }, 5000);
        
        // 测试3: 执行命令
        setTimeout(() => {
            testCount++;
            console.log(`\n${testCount}. 测试执行命令...`);
            
            const execQuery = {
                type: 'user_message',
                openclawPeers: [
                    {
                        id: 'client_1773641570043_94kgysbg0',
                        clientType: 'openclaw',
                        deviceInfo: null
                    }
                ],
                content: '执行命令: dir C:\\',
                timestamp: new Date().toISOString()
            };
            
            console.log(`   发送: ${execQuery.content}`);
            ws.send(JSON.stringify(execQuery));
            
        }, 9000);
        
        // 测试4: 普通消息
        setTimeout(() => {
            testCount++;
            console.log(`\n${testCount}. 测试普通消息...`);
            
            const normalQuery = {
                type: 'user_message',
                openclawPeers: [
                    {
                        id: 'client_1773641570043_94kgysbg0',
                        clientType: 'openclaw',
                        deviceInfo: null
                    }
                ],
                content: '你好，今天天气怎么样？',
                timestamp: new Date().toISOString()
            };
            
            console.log(`   发送: ${normalQuery.content}`);
            ws.send(JSON.stringify(normalQuery));
            
        }, 13000);
        
    }, 3000);
});

ws.on('message', (data) => {
    try {
        const msg = JSON.parse(data.toString());
        
        if (msg.type === 'welcome') {
            console.log(`📨 收到欢迎消息, clientId: ${msg.clientId}`);
        }
        
        if (msg.type === 'user_message_response') {
            console.log(`\n✅ 收到用户消息响应 (状态: ${msg.status}):`);
            
            if (msg.status === 'processing') {
                console.log(`   ⏳ 处理中: ${msg.response}`);
            } else if (msg.status === 'completed') {
                passedTests++;
                console.log(`   ✅ 处理完成: ${msg.response.substring(0, 100)}...`);
                console.log(`   结果类型: ${msg.result ? typeof msg.result : '无结果'}`);
            } else if (msg.status === 'error') {
                console.log(`   ❌ 处理错误: ${msg.response}`);
            } else if (msg.status === 'busy') {
                console.log(`   ⚠️ 执行器忙: ${msg.response}`);
            }
        }
        
        if (msg.type === 'echo') {
            // 忽略回显消息
        }
        
        if (msg.type === 'heartbeat') {
            // 忽略心跳
        }
        
    } catch (e) {
        console.log('收到消息:', data.toString().slice(0, 100));
    }
});

ws.on('error', (err) => {
    console.error('❌ WebSocket 错误:', err.message);
});

ws.on('close', () => {
    console.log('\n🔌 连接已关闭');
    console.log(`\n📊 测试结果: ${passedTests}/${testCount} 通过`);
    process.exit(passedTests === testCount ? 0 : 1);
});

// 设置测试超时
setTimeout(() => {
    console.log('\n⏰ 测试完成');
    ws.close();
}, 20000);
