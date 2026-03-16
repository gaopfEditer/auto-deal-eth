/**
 * 测试服务端指令发送
 * 模拟服务端向执行器发送指令
 */

const WebSocket = require('ws');

const WS_URL = 'ws://localhost:3123/api/ws?type=openclaw';

console.log('🔧 测试服务端指令发送');
console.log(`连接: ${WS_URL}`);

const ws = new WebSocket(WS_URL);

let clientId = null;
let executorClientId = null;

ws.on('open', () => {
    console.log('✅ 连接到服务端');
    
    // 等待执行器连接
    setTimeout(() => {
        console.log('\n📤 发送测试指令...');
        
        // 1. 发送 user_message 指令
        const userMessage = {
            type: 'user_message',
            openclawPeers: [
                {
                    id: 'client_1773640311120_azuqo47ay', // 从日志中获取的执行器clientId
                    clientType: 'openclaw',
                    deviceInfo: null
                }
            ],
            content: '测试指令：请帮我查看当前时间',
            timestamp: new Date().toISOString()
        };
        
        console.log('1. 发送 user_message 指令:', userMessage.content);
        ws.send(JSON.stringify(userMessage));
        
        // 2. 等待后发送 openclaw_next_role 指令
        setTimeout(() => {
            const openclawTask = {
                type: 'openclaw_next_role',
                nextRole: 'TestRole_2',
                payload: {
                    task: '测试任务',
                    parameters: { test: 'value' }
                },
                timestamp: new Date().toISOString()
            };
            
            console.log('2. 发送 openclaw_next_role 指令:', openclawTask.nextRole);
            ws.send(JSON.stringify(openclawTask));
            
        }, 2000);
        
        // 3. 等待后发送通用任务指令
        setTimeout(() => {
            const genericTask = {
                type: 'task',
                task_id: 'test_task_' + Date.now(),
                task_type: 'generic',
                parameters: {
                    command: 'echo "Hello from server"',
                    timeout: 5000
                },
                timestamp: new Date().toISOString()
            };
            
            console.log('3. 发送通用 task 指令:', genericTask.task_id);
            ws.send(JSON.stringify(genericTask));
            
        }, 4000);
        
    }, 3000);
});

ws.on('message', (data) => {
    try {
        const msg = JSON.parse(data.toString());
        
        if (msg.type === 'welcome') {
            clientId = msg.clientId;
            console.log(`📨 收到欢迎消息, clientId: ${clientId}`);
        }
        
        if (msg.type === 'user_message_response') {
            console.log('\n✅ 收到 user_message 响应:');
            console.log(`   响应: ${msg.response}`);
            console.log(`   状态: ${msg.status}`);
            console.log(`   执行器: ${msg.executor_id}`);
        }
        
        if (msg.type === 'task_result') {
            console.log('\n✅ 收到任务结果:');
            console.log(`   任务ID: ${msg.task_id}`);
            console.log(`   状态: ${msg.status}`);
            console.log(`   结果: ${msg.result?.substring(0, 100)}...`);
        }
        
        if (msg.type === 'echo') {
            // 忽略回显消息
        }
        
        if (msg.type === 'heartbeat') {
            console.log(`💓 收到心跳 from ${msg.executor_id}`);
        }
        
    } catch (e) {
        console.log('收到消息:', data.toString().slice(0, 100));
    }
});

ws.on('error', (err) => {
    console.error('❌ WebSocket 错误:', err.message);
});

ws.on('close', () => {
    console.log('🔌 连接已关闭');
});

// 设置测试超时
setTimeout(() => {
    console.log('\n⏰ 测试完成');
    ws.close();
    process.exit(0);
}, 10000);
