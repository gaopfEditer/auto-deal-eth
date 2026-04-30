const WebSocket = require('ws');
const http = require('http');

const WS_URL = 'ws://localhost:3123/api/ws?type=openclaw';
const EXECUTOR_ID = process.env.EXECUTOR_ID || 'openclaw_3123';

class Executor3123 {
    constructor() {
        this.ws = null;
        this.clientId = null;
        this.isBusy = false;
        this.currentTask = null;
    }

    connect() {
        console.log(`[Executor] Connecting to: ${WS_URL}`);
        
        return new Promise((resolve, reject) => {
            this.ws = new WebSocket(WS_URL);

            this.ws.on('open', () => {
                console.log('[Executor] WebSocket connected');
                resolve(true);
            });

            this.ws.on('message', (data) => {
                this.handleMessage(data.toString());
            });

            this.ws.on('error', (err) => {
                console.error('[Executor] WebSocket error:', err.message);
                reject(err);
            });

            this.ws.on('close', () => {
                console.log('[Executor] WebSocket closed');
                process.exit(0);
            });
        });
    }

    handleMessage(message) {
        try {
            const data = JSON.parse(message);
            console.log(`[Executor] Received: ${data.type}`);

            if (data.type === 'welcome') {
                this.clientId = data.clientId;
                console.log(`[Executor] Got clientId: ${this.clientId}`);
            } else if (data.type === 'openclaw_next_role') {
                this.processTask(data.nextRole);
            }
        } catch (e) {
            console.log(`[Executor] Raw message: ${message.slice(0, 100)}`);
        }
    }

    async processTask(nextRole) {
        if (this.isBusy) {
            console.log(`[Executor] BUSY, current: ${this.currentTask}`);
            return;
        }

        this.isBusy = true;
        this.currentTask = nextRole;
        console.log(`[Executor] Processing task: ${nextRole}`);

        // 处理任务...
        const result = {
            status: 'completed',
            nextRole: nextRole,
            executor: EXECUTOR_ID,
            result: `Processed ${nextRole}`,
            timestamp: new Date().toISOString()
        };

        await this.sendWebhook(result);

        this.isBusy = false;
        this.currentTask = null;
    }

    sendWebhook(data) {
        return new Promise((resolve, reject) => {
            const body = JSON.stringify(data);
            
            const req = http.request({
                hostname: 'localhost',
                port: 3123,
                path: '/api/openclaw/webhook',
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Content-Length': Buffer.byteLength(body)
                }
            }, (res) => {
                let responseData = '';
                res.on('data', chunk => responseData += chunk);
                res.on('end', () => {
                    console.log(`[Executor] Webhook response: ${res.statusCode}`);
                    resolve(responseData);
                });
            });

            req.on('error', reject);
            req.write(body);
            req.end();
        });
    }

    sendHeartbeat() {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            this.ws.send(JSON.stringify({
                type: 'heartbeat',
                executor_id: EXECUTOR_ID,
                client_id: this.clientId
            }));
        }
    }

    async run() {
        console.log(`[Executor] Starting ${EXECUTOR_ID}`);
        
        try {
            await this.connect();
            
            // 心跳
            setInterval(() => this.sendHeartbeat(), 30000);
            
            console.log('[Executor] Running...');
            
        } catch (err) {
            console.error('[Executor] Failed to connect:', err.message);
            process.exit(1);
        }
    }
}

const executor = new Executor3123();
executor.run();
