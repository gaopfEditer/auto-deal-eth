/**
 * 测试设备信息上报和用户消息处理
 */

const WebSocket = require('ws');
const http = require('http');

const PORT = 3123;
const WS_URL = `ws://localhost:${PORT}/api/ws?type=openclaw`;

function testDeviceInfoAndUserMessage() {
    return new Promise((resolve, reject) => {
        console.log('测试设备信息上报和用户消息处理');
        console.log(`连接: ${WS_URL}`);
        
        const ws = new WebSocket(WS_URL);
        let receivedDeviceInfo = false;
        let receivedUserMessageResponse = false;
        const timeout = setTimeout(() => {
            ws.close();
            reject(new Error('测试超时'));
        }, 10000);

        ws.on('open', () => {
            console.log('✅ WebSocket 连接成功');
            
            // 等待设备信息上报
            setTimeout(() => {
                // 发送用户消息测试
                const userMessage = {
                    type: 'user_message',
                    message_id: 'test_user_msg_' + Date.now(),
                    content: '你好，请帮我搜索一下OpenClaw的文档',
                    timestamp: new Date().toISOString()
                };
                
                console.log('发送用户消息:', userMessage.content);
                ws.send(JSON.stringify(userMessage));
            }, 1000);
        });

        ws.on('message', (data) => {
            try {
                const msg = JSON.parse(data.toString());
                console.log(`收到消息: ${msg.type}`);
                
                if (msg.type === 'device_info') {
                    receivedDeviceInfo = true;
                    console.log('✅ 收到设备信息:', {
                        executor_id: msg.executor_id,
                        platform: msg.device?.platform,
                        node_version: msg.device?.node_version
                    });
                }
                
                if (msg.type === 'user_message_response') {
                    receivedUserMessageResponse = true;
                    console.log('✅ 收到用户消息响应:', msg.response);
                    
                    if (receivedDeviceInfo && receivedUserMessageResponse) {
                        clearTimeout(timeout);
                        ws.close();
                        resolve({
                            deviceInfo: receivedDeviceInfo,
                            userMessageResponse: receivedUserMessageResponse
                        });
                    }
                }
            } catch (e) {
                console.log('收到原始消息:', data.toString().slice(0, 100));
            }
        });

        ws.on('error', (err) => {
            clearTimeout(timeout);
            reject(err);
        });

        ws.on('close', () => {
            clearTimeout(timeout);
            if (!receivedDeviceInfo || !receivedUserMessageResponse) {
                reject(new Error(`测试未完成: deviceInfo=${receivedDeviceInfo}, userMessageResponse=${receivedUserMessageResponse}`));
            }
        });
    });
}

// 运行测试
testDeviceInfoAndUserMessage()
    .then((result) => {
        console.log('\n✅ 测试通过!');
        console.log('结果:', result);
        process.exit(0);
    })
    .catch((err) => {
        console.error('\n❌ 测试失败:', err.message);
        process.exit(1);
    });
