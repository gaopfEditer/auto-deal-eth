/**
 * 测试 OpenClaw WebSocket 连接与 Webhook 接口
 *
 * 1. 连接 ws://localhost:3123/api/ws?type=openclaw
 * 2. 收到 welcome 后上报设备信息（系统类型、版本、用户名等）
 * 3. 调用 POST http://localhost:3123/api/openclaw/webhook 发送 nextRole
 * 4. 验证 WebSocket 收到 openclaw_next_role 消息
 *
 * 运行: node test/test-openclaw-ws-webhook.js
 * 端口: PORT=3123 node test/test-openclaw-ws-webhook.js（可选）
 */

const http = require('http');
const os = require('os');
const WebSocket = require('ws');

/** 采集当前设备信息（系统类型、Win 型号、用户名等） */
function getDeviceInfo() {
  const platform = os.platform();
  const platformNames = { win32: 'Windows', darwin: 'macOS', linux: 'Linux' };
  return {
    systemType: platformNames[platform] || platform,
    platform,
    release: os.release(),
    hostname: os.hostname(),
    username: process.env.USERNAME || process.env.USER || process.env.LOGNAME || 'unknown',
    arch: os.arch(),
  };
}

const PORT = parseInt(process.env.PORT || '3123', 10);
const WS_URL = `ws://localhost:${PORT}/api/ws?type=openclaw`;
const WEBHOOK_URL = `/api/openclaw/webhook`;

function callWebhook(nextRole) {
  return new Promise((resolve, reject) => {
    const body = JSON.stringify({ nextRole });
    const req = http.request(
      {
        hostname: 'localhost',
        port: PORT,
        path: WEBHOOK_URL,
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Content-Length': Buffer.byteLength(body, 'utf8'),
        },
        timeout: 5000,
      },
      (res) => {
        let data = '';
        res.on('data', (chunk) => (data += chunk));
        res.on('end', () => {
          try {
            resolve({ statusCode: res.statusCode, body: data ? JSON.parse(data) : null });
          } catch (e) {
            resolve({ statusCode: res.statusCode, body: data });
          }
        });
      }
    );
    req.on('error', reject);
    req.on('timeout', () => {
      req.destroy();
      reject(new Error('Webhook request timeout'));
    });
    req.write(body);
    req.end();
  });
}

function runTest() {
  return new Promise((resolve, reject) => {
    console.log('> 连接 WebSocket:', WS_URL);
    const ws = new WebSocket(WS_URL);

    const timeout = setTimeout(() => {
      if (!receivedNextRole) {
        ws.close();
        reject(new Error('超时：未在 5 秒内收到 openclaw_next_role'));
      }
    }, 5000);

    let receivedWelcome = false;
    let receivedNextRole = false;
    const receivedRoles = [];

    ws.on('open', () => {
      console.log('> WebSocket 已连接');
    });

    ws.on('message', (raw) => {
      try {
        const msg = JSON.parse(raw.toString());
        if (msg.type === 'welcome') {
          receivedWelcome = true;
          console.log('> 收到 welcome, clientId:', msg.clientId);
          const deviceInfo = getDeviceInfo();
          console.log('> 上报设备信息:', JSON.stringify(deviceInfo, null, 2));
          ws.send(JSON.stringify({ type: 'connected', clientId: msg.clientId, deviceInfo }));
          // 收到 welcome 并上报设备信息后，再调用 webhook
          setTimeout(() => {
            console.log('> 调用 OpenClaw Webhook, nextRole: TestRole_1');
            callWebhook('TestRole_1')
              .then((result) => {
                console.log('> Webhook 响应:', result.statusCode, JSON.stringify(result.body, null, 2));
                if (result.statusCode !== 200) {
                  clearTimeout(timeout);
                  ws.close();
                  reject(new Error(`Webhook 返回 ${result.statusCode}`));
                }
              })
              .catch((err) => {
                clearTimeout(timeout);
                ws.close();
                reject(err);
              });
          }, 200);
        }
        if (msg.type === 'openclaw_command' || msg.type === 'user_message') {
          if (msg.type === 'user_message') {
            console.log('> 收到 user_message 原样内容:', msg.content != null ? msg.content : msg);
          } else {
            console.log('> 收到 openclaw_command:', msg.session_selected ? 'session_selected' : '');
          }
          if (msg.openclawPeers && Array.isArray(msg.openclawPeers)) {
            console.log('> 附带 openclawPeers 数量:', msg.openclawPeers.length);
            msg.openclawPeers.forEach((p, i) => {
              console.log(`>   [${i}] id=${p.id} deviceInfo=`, p.deviceInfo || '(无)');
            });
          }
        }
        if (msg.type === 'openclaw_next_role') {
          receivedNextRole = true;
          receivedRoles.push(msg.nextRole);
          console.log('> 收到 openclaw_next_role:', msg.nextRole);
          if (msg.openclawPeers && Array.isArray(msg.openclawPeers)) {
            console.log('> 附带 openclawPeers 数量:', msg.openclawPeers.length);
            msg.openclawPeers.forEach((p, i) => {
              console.log(`>   [${i}] id=${p.id} deviceInfo=`, p.deviceInfo || '(无)');
            });
          }
          clearTimeout(timeout);
          console.log('> 保持连接 50 秒，便于在页面 OpenClaw 会话列表中查看本连接');
          setTimeout(() => {
            ws.close();
            resolve(receivedRoles);
          }, 50000);
        }
      } catch (e) {
        console.log('> 收到原始消息:', raw.toString().slice(0, 80));
      }
    });

    ws.on('error', (err) => {
      clearTimeout(timeout);
      reject(err);
    });

    ws.on('close', () => {
      clearTimeout(timeout);
      if (!receivedNextRole) {
        reject(new Error('WebSocket 已关闭，未收到 openclaw_next_role'));
      }
    });
  });
}

const deviceInfo = getDeviceInfo();
console.log('OpenClaw 测试 (WebSocket + Webhook)');
console.log('端口:', PORT);
console.log('本机设备:', deviceInfo.systemType, deviceInfo.release, '| 用户:', deviceInfo.username, '| 主机:', deviceInfo.hostname);
console.log('');

runTest()
  .then((roles) => {
    console.log('');
    console.log('✅ 测试通过，收到的 nextRole 序列:', roles);
    process.exit(0);
  })
  .catch((err) => {
    console.error('');
    console.error('❌ 测试失败:', err.message);
    process.exit(1);
  });
