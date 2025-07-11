# sose-25-se3s Prototyping Assignment

A sharded, replicated, and resilient **scalable counter** system built with Flask, Consistent Hashing, and Docker. 
Supports horizontal and vertical scaling, replication for high availability, 
and a write queue with strategy for sidelining traffic.

---

## Architecture Overview

This system consists of:

- **Store Nodes** (primary & secondary): Persistent key-value stores.
- **Queue**: Accepts and rate-limits write requests.
- **API**: Front-facing service handling reads and forwarding writes to the queue.
- **Nginx**: Reverse proxy to route requests to the API.
- **Consistent Hashing**: Used to determine which store node is responsible for a given key.


           ┌────────────┐
           │   Client   │
           └─────┬──────┘
                 │
            ┌────▼────┐
            │  NGINX  │ (port 8000)
            └────┬────┘
                 │
            ┌────▼────┐
            │   API   │ (Flask app)
            └────┬────┘
         ┌───────┴────────┐
         │   Queue (Flask)│
         └───────┬────────┘ 
    ┌────────────▼────────────┐
    │     Store Primaries     │
    │(store1 & store2 @ :9000)│
    └───────────┬─────────────┘
      ┌─────────▼───────────┐
      │  Store Secondaries  │
      │ (replicated async)  │
      └─────────────────────┘

## Quick Start
### 1. Start the API
```bash
docker-compose up --build
```
The API will be accessable at:
http://localhost:8000

### 2. Cleanup (Stop Services)
To stop all running Docker containers associated with this project and free up resources, run:
```bash
docker compose down
```

## Instructed DEMO
Explore [here](./DEMO.md) for an instructed demo of this scalable system.