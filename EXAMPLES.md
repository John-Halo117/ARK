# ARK Integration Examples

## Publishing Events to ARK

### Example 1: Code Analysis Request (Python)

```python
import asyncio
import json
import nats

async def analyze_code():
    nc = await nats.connect("nats://localhost:4222")
    js = nc.jetstream()
    
    # Publish capability request
    await js.publish("ark.call.opencode.code.analyze", json.dumps({
        "request_id": "analysis-001",
        "params": {
            "source": """
def calculate_fibonacci(n):
    if n <= 1:
        return n
    return calculate_fibonacci(n-1) + calculate_fibonacci(n-2)
""",
            "language": "python"
        }
    }).encode())
    
    print("Analysis request published")
    await nc.close()

asyncio.run(analyze_code())
```

### Example 2: System Health Check (Python)

```python
import asyncio
import json
import nats

async def check_health():
    nc = await nats.connect("nats://localhost:4222")
    js = nc.jetstream()
    
    # Request system health
    await js.publish("ark.call.openwolf.system.health", json.dumps({
        "request_id": "health-001",
        "params": {
            "metrics": {
                "cpu_usage": 45.2,
                "memory_usage": 67.8,
                "disk_usage": 52.1
            }
        }
    }).encode())
    
    print("Health check published")
    await nc.close()

asyncio.run(check_health())
```

### Example 3: External Action (Email via Composio)

```python
import asyncio
import json
import nats

async def send_email():
    nc = await nats.connect("nats://localhost:4222")
    js = nc.jetstream()
    
    # Request external action
    await js.publish("ark.call.composio.external.email", json.dumps({
        "request_id": "email-001",
        "params": {
            "to": "user@example.com",
            "subject": "System Alert",
            "body": "ASHI score dropped below threshold"
        }
    }).encode())
    
    print("Email action published")
    await nc.close()

asyncio.run(send_email())
```

---

## Listening for Responses

### Example 4: Subscribe to Replies

```python
import asyncio
import json
import nats

async def listen_for_reply(request_id):
    nc = await nats.connect("nats://localhost:4222")
    js = nc.jetstream()
    
    async def message_handler(msg):
        data = json.loads(msg.data.decode())
        print(f"Reply received: {json.dumps(data, indent=2)}")
        await nc.close()
    
    # Subscribe to reply topic
    await nc.subscribe(f"ark.reply.{request_id}", cb=message_handler)
    
    # Keep running
    await asyncio.sleep(10)

asyncio.run(listen_for_reply("analysis-001"))
```

---

## n8n Integration

### Example 5: n8n Webhook Trigger → ARK Capability

**n8n Workflow Setup:**

1. Create HTTP trigger node
2. Add webhook endpoint: `/api/webhook/ark-trigger`
3. Add HTTP request node with these settings:
   ```
   Method: POST
   URL: http://ark-nats:4222/api/call
   Headers: Content-Type: application/json
   Body:
   {
     "capability": "code.analyze",
     "source": "{{ $json.code }}",
     "language": "{{ $json.language }}"
   }
   ```
4. Add webhook response node to return result

**Trigger from external app:**
```bash
curl -X POST http://localhost:5678/api/webhook/ark-trigger \
  -H "Content-Type: application/json" \
  -d '{
    "code": "def hello(): pass",
    "language": "python"
  }'
```

---

## Home Assistant Integration

### Example 6: Automation Triggered by ASHI Alert

**automations.yaml:**
```yaml
automation:
  - alias: "ASHI Health Alert"
    description: "Alert when system health degrades"
    trigger:
      platform: template
      value_template: "{{ state_attr('ark.ashi', 'score') | int < 60 }}"
    action:
      - service: notify.mobile_app_phone
        data:
          title: "ARK System Alert"
          message: "ASHI score: {{ state_attr('ark.ashi', 'score') }}"
      - service: input_text.set_value
        target:
          entity_id: input_text.ark_status
        data:
          value: "DEGRADED"
```

### Example 7: Home Assistant Action → ARK Capability

**automations.yaml:**
```yaml
automation:
  - alias: "Analyze Code on Button Press"
    trigger:
      platform: state
      entity_id: button.analyze_code
      to: 'pressed'
    action:
      - service: mqtt.publish
        data:
          topic: "ark/capability/code.analyze"
          payload_template: |
            {
              "request_id": "ha-{{ now().timestamp() | int }}",
              "params": {
                "source": "{{ states('input_text.code_input') }}",
                "language": "python"
              }
            }
```

---

## DuckDB Queries

### Example 8: Query Events

```sql
-- Recent capability calls
SELECT type, payload, created_at 
FROM events 
WHERE type LIKE 'ark.call%' 
ORDER BY created_at DESC 
LIMIT 20;

-- Count by service
SELECT 
  payload->>'service' as service,
  COUNT(*) as call_count
FROM events 
WHERE type LIKE 'ark.call%'
GROUP BY service;

-- Anomalies detected
SELECT 
  created_at,
  payload->>'metric' as metric,
  payload->>'value' as value
FROM events 
WHERE type = 'ark.anomaly.detected'
ORDER BY created_at DESC;
```

### Example 9: Insert System State

```sql
-- Record ASHI score
INSERT INTO state (key, value) 
VALUES ('ashi_score', '{"score": 85, "level": "good"}');

-- Update service capability mapping
INSERT INTO state (key, value) 
VALUES ('opencode_capabilities', '["code.analyze", "code.generate", "reasoning.plan"]');
```

---

## Custom Agent Template

### Example 10: Build Your Own Agent

Create `/agents/finance-agent/agent.py`:

```python
#!/usr/bin/env python3
import asyncio
import json
import logging
import os
import uuid
from datetime import datetime
from typing import Dict, Any

import nats

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('FinanceAgent')

class FinanceAgent:
    def __init__(self):
        self.service_name = "finance"
        self.instance_id = os.environ.get('INSTANCE_ID', str(uuid.uuid4())[:12])
        self.nats_url = os.environ.get('NATS_URL', 'nats://nats:4222')
        
        self.capabilities = [
            "finance.ledger.entry",
            "finance.budget.check",
            "finance.forecast"
        ]
        
        self.nc = None
        self.js = None
        logger.info(f"FinanceAgent init (id={self.instance_id})")
    
    async def connect(self):
        self.nc = await nats.connect(self.nats_url)
        self.js = self.nc.jetstream()
        logger.info("Connected to NATS")
    
    async def register(self):
        await self.nc.publish("ark.mesh.register", json.dumps({
            "service": self.service_name,
            "instance_id": self.instance_id,
            "capabilities": self.capabilities,
            "ttl": 10
        }).encode())
        logger.info(f"Registered: {self.capabilities}")
    
    async def subscribe_calls(self):
        sub = await self.nc.subscribe(f"ark.call.{self.service_name}.*")
        
        async for msg in sub.messages:
            subject_parts = msg.subject.split('.')
            capability = subject_parts[-1]
            
            request = json.loads(msg.data.decode())
            request_id = request.get('request_id', str(uuid.uuid4())[:12])
            params = request.get('params', {})
            
            # Handle capability
            if capability == "finance.ledger.entry":
                result = await self.add_entry(params)
            elif capability == "finance.budget.check":
                result = await self.check_budget(params)
            else:
                result = {"error": f"Unknown: {capability}"}
            
            # Reply
            await self.js.publish(f"ark.reply.{request_id}", json.dumps(result).encode())
    
    async def add_entry(self, params: Dict[str, Any]):
        amount = params.get('amount', 0)
        category = params.get('category', 'other')
        
        # Save to DuckDB would happen here
        return {
            "agent": self.service_name,
            "capability": "finance.ledger.entry",
            "amount": amount,
            "category": category,
            "success": True
        }
    
    async def check_budget(self, params: Dict[str, Any]):
        category = params.get('category', 'all')
        
        return {
            "agent": self.service_name,
            "capability": "finance.budget.check",
            "category": category,
            "remaining": 500.00
        }
    
    async def heartbeat_loop(self):
        while True:
            await asyncio.sleep(5)
            await self.nc.publish("ark.mesh.heartbeat", json.dumps({
                "service": self.service_name,
                "instance_id": self.instance_id,
                "load": 0.0,
                "healthy": True
            }).encode())
    
    async def run(self):
        try:
            await self.connect()
            await self.register()
            logger.info("FinanceAgent started")
            
            await asyncio.gather(
                self.subscribe_calls(),
                self.heartbeat_loop()
            )
        except KeyboardInterrupt:
            logger.info("Shutdown")
        finally:
            if self.nc:
                await self.nc.close()

if __name__ == "__main__":
    agent = FinanceAgent()
    asyncio.run(agent.run())
```

Create `Dockerfile.finance`:
```dockerfile
FROM python:3.11-slim
RUN pip install --no-cache-dir nats-py
COPY agents/finance-agent/agent.py /app/agent.py
ENV INSTANCE_ID=finance-0
ENV NATS_URL=nats://nats:4222
CMD ["python", "/app/agent.py"]
```

Add to docker-compose.yml:
```yaml
finance:
  build:
    context: .
    dockerfile: Dockerfile.finance
  container_name: ark-finance
  environment:
    NATS_URL: nats://nats:4222
  depends_on:
    nats:
      condition: service_healthy
  networks:
    - ark-net
```

Start it:
```bash
docker-compose build finance
docker-compose up -d finance
```

---

## Stress Testing

### Example 11: Load Test with Python

```python
import asyncio
import json
import time
import nats

async def load_test(num_requests=1000):
    nc = await nats.connect("nats://localhost:4222")
    js = nc.jetstream()
    
    start = time.time()
    
    for i in range(num_requests):
        await js.publish("ark.call.opencode.code.analyze", json.dumps({
            "request_id": f"load-{i}",
            "params": {
                "source": f"def func_{i}(): pass",
                "language": "python"
            }
        }).encode())
        
        if (i + 1) % 100 == 0:
            print(f"Published {i + 1}/{num_requests}")
    
    elapsed = time.time() - start
    throughput = num_requests / elapsed
    
    print(f"\nLoad test complete:")
    print(f"  Requests: {num_requests}")
    print(f"  Time: {elapsed:.2f}s")
    print(f"  Throughput: {throughput:.0f} req/s")
    
    await nc.close()

asyncio.run(load_test(1000))
```

---

## Mesh Inspection

### Example 12: Query Mesh via REST API

```bash
# Get full mesh status
curl http://localhost:7000/api/mesh | jq

# Route capability to best instance
curl http://localhost:7000/api/route/code.analyze | jq

# Get service details
curl http://localhost:7000/api/service/opencode | jq

# Autoscaler instances
curl http://localhost:7001/api/instances/opencode | jq

# Manually spawn instance
curl -X POST http://localhost:7001/api/spawn \
  -H "Content-Type: application/json" \
  -d '{"service": "opencode"}' | jq
```

---

**ARK is extensible. Add agents, extend capabilities, evolve the system.**
