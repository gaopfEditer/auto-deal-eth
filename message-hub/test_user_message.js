/**
 * 测试用户消息发送
 * 直接连接到服务端发送用户消息
 */

const WebSocket = require('ws');

const WS_URL = 'ws://localhost:3123/api/ws?type=openclaw';

console.log('🔍 连接到服务端测试用户消息处理...');
console.log(`连接: ${WS_URL}`);

const ws = new WebSocket(WS_URL);

ws.on('open', () => {
    console.log('✅ 连接到服务端');
    
    // 等待一下让执行器连接
    setTimeout(() => {
        console.log('\n📤 发送用户消息...');
        
        const userMessage = {
            type: 'user_message',
            openclawPeers: [
                {
                    id: 'client_1773635360695_47sk6ogdy', // 从执行器日志中获取的clientId
                    clientType: 'openclaw',
                    deviceInfo: null
                }
            ],
            content: '你好，请帮我搜索一下OpenClaw的文档',
            timestamp: new Date().toISOString()
        };
        
        console.log('消息内容:', userMessage.content);
        ws.send(JSON.stringify(userMessage));
        
        console.log('\n⏳ 等待响应...');
    }, 2000);
});

ws.on('message', (data) => {
    try {
        const msg = JSON.parse(data.toString());
        console.log(`\n📨 收到消息: ${msg.type}`);
        
        if (msg.type === 'welcome') {
            console.log(`欢迎消息, clientId: ${msg.clientId}`);
        }
        
        if (msg.type === 'user_message_response') {
            console.log('✅ 收到用户消息响应!');
            console.log(`响应: ${msg.response}`);
            console.log(`状态: ${msg.status}`);
            console.log(`执行器: ${msg.executor_id}`);
            
            // 测试成功，关闭连接
            setTimeout(() => {
                ws.close();
                console.log('\n🎉 测试成功! 执行器正确处理了用户消息。');
                process.exit(0);
            }, 1000);
        }
        
        if (msg.type === 'user_message_error') {
            console.log('❌ 收到用户消息错误响应');
            console.log(`错误: ${msg.error}`);
            
            setTimeout(() => {
                ws.close();
                console.log('\n⚠️ 测试完成，但有错误。');
                process.exit(1);
            }, 1000);
        }
        
        if (msg.type === 'echo') {
            console.log(`回显: ${msg.message}`);
        }
        
    } catch (e) {
        console.log('收到原始消息:', data.toString().slice(0, 100));
    }
});

ws.on('error', (err) => {
    console.error('❌ WebSocket 错误:', err.message);
    process.exit(1);
});

ws.on('close', () => {
    console.log('🔌 连接已关闭');
});

// 设置超时
setTimeout(() => {
    console.log('\n⏰ 测试超时，未收到用户消息响应');
    ws.close();
    process.exit(1);
}, 10000);
