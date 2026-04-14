#!/usr/bin/env python3
"""
OpenWolf Agent - Anomaly detection and system health inference
Monitors metrics, detects anomalies, computes ASHI health score
"""

import asyncio
import json
import logging
import os
import uuid
from datetime import datetime
from typing import Dict, Any, List
from statistics import mean, stdev

import nats
from nats.errors import Error as NATSError

from ark.security import sanitize_string, validate_payload, safe_log_event
from ark.maintenance import ResilientNATSConnection, ShutdownCoordinator, HealthCheck

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger('OpenWolf')


class OpenWolfAgent:
    """System health and anomaly detection agent"""
    
    def __init__(self):
        self.service_name = "openwolf"
        self.instance_id = os.environ.get('INSTANCE_ID', str(uuid.uuid4())[:12])
        self.nats_url = os.environ.get('NATS_URL', 'nats://nats:4222')
        
        self.capabilities = [
            "anomaly.detect",
            "system.health",
            "metrics.ingest",
            "ashi.compute"
        ]
        
        self.nc = None
        self.js = None
        self.request_count = 0
        self._nats = ResilientNATSConnection(self.nats_url)
        self.shutdown = ShutdownCoordinator()
        self.health = HealthCheck(self.service_name)
        self.health.register("nats", lambda: self._nats.is_connected)
        
        # Metric baselines and history
        self.metric_history: Dict[str, List[float]] = {}
        self._max_metric_history = 100
        self.ashi_score = 100
        
        logger.info("OpenWolf initialized (instance=%s)", self.instance_id)
    
    async def connect(self):
        """Connect to NATS with resilient reconnection"""
        self.nc = await self._nats.connect()
        self.js = self._nats.js
        logger.info("Connected to NATS")
    
    async def register(self):
        """Register with mesh"""
        event = {
            "service": self.service_name,
            "instance_id": self.instance_id,
            "capabilities": self.capabilities,
            "metadata": {
                "version": "1.0.0",
                "started_at": datetime.utcnow().isoformat()
            },
            "ttl": 10
        }
        
        await self.nc.publish("ark.mesh.register", json.dumps(event).encode())
        logger.info(f"Registered with mesh: {self.capabilities}")
    
    async def heartbeat_loop(self):
        """Send periodic heartbeats"""
        while True:
            await asyncio.sleep(5)
            
            try:
                await self.nc.publish("ark.mesh.heartbeat", json.dumps({
                    "service": self.service_name,
                    "instance_id": self.instance_id,
                    "load": self.request_count / 100.0,
                    "healthy": True,
                    "timestamp": datetime.utcnow().isoformat()
                }).encode())
                
                self.request_count = 0
                
            except Exception as e:
                logger.error(f"Heartbeat error: {e}")
    
    async def subscribe_calls(self):
        """Subscribe to capability calls"""
        try:
            sub = await self.nc.subscribe(f"ark.call.{self.service_name}.*")
            logger.info(f"Subscribed to capability calls")
            
            async for msg in sub.messages:
                try:
                    subject_parts = msg.subject.split('.')
                    capability = subject_parts[-1] if len(subject_parts) >= 4 else "unknown"
                    
                    request = json.loads(msg.data.decode())
                    request_id = request.get('request_id', str(uuid.uuid4())[:12])
                    params = request.get('params', {})
                    
                    logger.info(f"Processing capability: {capability}")
                    
                    result = await self.handle_capability(capability, params)
                    
                    reply_topic = f"ark.reply.{request_id}"
                    await self.js.publish(reply_topic, json.dumps(result).encode())
                    
                    self.request_count += 1
                    
                except Exception as e:
                    logger.error(f"Error processing call: {e}")
        
        except NATSError as e:
            logger.error(f"Subscription error: {e}")
    
    async def subscribe_metrics(self):
        """Subscribe to metric streams"""
        try:
            sub = await self.nc.subscribe("ark.metrics.*")
            logger.info("Subscribed to metrics")
            
            async for msg in sub.messages:
                try:
                    subject_parts = msg.subject.split('.')
                    metric_name = '.'.join(subject_parts[2:]) if len(subject_parts) > 2 else "unknown"
                    
                    event = json.loads(msg.data.decode())
                    value = event.get('value', 0)
                    
                    # Store in history
                    if metric_name not in self.metric_history:
                        self.metric_history[metric_name] = []
                    
                    self.metric_history[metric_name].append(value)
                    
                    # Keep only last 100 samples
                    if len(self.metric_history[metric_name]) > 100:
                        self.metric_history[metric_name].pop(0)
                    
                    # Run anomaly detection
                    is_anomaly = await self.check_anomaly(metric_name, value)
                    
                    if is_anomaly:
                        await self.js.publish("ark.anomaly.detected", json.dumps({
                            "metric": metric_name,
                            "value": value,
                            "timestamp": datetime.utcnow().isoformat()
                        }).encode())
                
                except Exception as e:
                    logger.error(f"Error processing metric: {e}")
        
        except NATSError as e:
            logger.error(f"Subscription error: {e}")
    
    async def handle_capability(self, capability: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Process a capability request"""
        if capability == "anomaly.detect":
            return await self.detect_anomaly(params)
        elif capability == "system.health":
            return await self.compute_health(params)
        elif capability == "metrics.ingest":
            return await self.ingest_metric(params)
        elif capability == "ashi.compute":
            return await self.compute_ashi(params)
        else:
            return {"error": f"Unknown capability: {capability}"}
    
    async def check_anomaly(self, metric_name: str, value: float) -> bool:
        """Check if metric is anomalous"""
        history = self.metric_history.get(metric_name, [])
        
        if len(history) < 5:
            return False
        
        try:
            avg = mean(history[:-1])
            if len(history) > 1:
                std = stdev(history[:-1]) or 1
            else:
                std = 1
            
            # Z-score: 3 standard deviations is anomaly
            z_score = abs(value - avg) / std
            return z_score > 3
        
        except Exception:
            return False
    
    async def detect_anomaly(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Detect anomalies in metric data"""
        metric = params.get('metric', '')
        value = params.get('value', 0)
        
        is_anomaly = await self.check_anomaly(metric, value)
        
        result = {
            "agent": self.service_name,
            "instance_id": self.instance_id,
            "capability": "anomaly.detect",
            "metric": metric,
            "value": value,
            "is_anomaly": is_anomaly,
            "severity": "high" if is_anomaly else "normal",
            "timestamp": datetime.utcnow().isoformat()
        }
        
        logger.info(f"Anomaly check for {metric}: {is_anomaly}")
        return result
    
    async def ingest_metric(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Ingest a system metric with bounds checking"""
        metric_name = sanitize_string(params.get('name', ''), 128)
        value = params.get('value', 0)
        try:
            value = float(value)
        except (TypeError, ValueError):
            return {"error": "value must be numeric"}
        
        if metric_name not in self.metric_history:
            self.metric_history[metric_name] = []
        
        self.metric_history[metric_name].append(value)
        if len(self.metric_history[metric_name]) > self._max_metric_history:
            self.metric_history[metric_name].pop(0)
        
        result = {
            "agent": self.service_name,
            "instance_id": self.instance_id,
            "capability": "metrics.ingest",
            "metric": metric_name,
            "value": value,
            "samples": len(self.metric_history[metric_name]),
            "timestamp": datetime.utcnow().isoformat()
        }
        
        logger.info(f"Ingested metric: {metric_name} = {value}")
        return result
    
    async def compute_health(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Compute overall system health"""
        metrics = params.get('metrics', {})
        
        anomaly_count = 0
        for metric_name, value in metrics.items():
            if await self.check_anomaly(metric_name, value):
                anomaly_count += 1
        
        health_score = max(0, 100 - (anomaly_count * 20))
        status = "healthy" if health_score >= 80 else "degraded" if health_score >= 50 else "critical"
        
        result = {
            "agent": self.service_name,
            "instance_id": self.instance_id,
            "capability": "system.health",
            "health_score": health_score,
            "status": status,
            "anomalies": anomaly_count,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        logger.info(f"System health: {status} (score={health_score})")
        return result
    
    async def compute_ashi(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Compute ASHI (ARK System Health Index)"""
        # Composite of all metrics and system state
        anomaly_count = 0
        for history in self.metric_history.values():
            if history:
                value = history[-1]
                metric_name = list(self.metric_history.keys())[
                    list(self.metric_history.values()).index(history)
                ]
                if await self.check_anomaly(metric_name, value):
                    anomaly_count += 1
        
        self.ashi_score = max(0, 100 - (anomaly_count * 15))
        
        result = {
            "agent": self.service_name,
            "instance_id": self.instance_id,
            "capability": "ashi.compute",
            "ashi_score": self.ashi_score,
            "level": "optimal" if self.ashi_score >= 90 else "good" if self.ashi_score >= 70 else "fair" if self.ashi_score >= 50 else "critical",
            "anomalies": anomaly_count,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        logger.info(f"ASHI computed: {self.ashi_score}")
        return result
    
    async def run(self):
        """Main agent loop with graceful shutdown"""
        try:
            self.shutdown.install_signal_handlers()
            await self.connect()
            await self.register()
            
            logger.info("OpenWolf agent started")
            
            await asyncio.gather(
                self.subscribe_calls(),
                self.subscribe_metrics(),
                self.heartbeat_loop()
            )
        
        except KeyboardInterrupt:
            logger.info("Shutting down...")
        finally:
            await self._nats.close()


async def main():
    agent = OpenWolfAgent()
    await agent.run()


if __name__ == "__main__":
    asyncio.run(main())
