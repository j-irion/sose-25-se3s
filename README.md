# sose-25-se3s Prototyping Assignment

A sharded, replicated, and resilient **scalable counter** system. 
Supports horizontal and vertical scaling, replication for high availability, sharding for isolation,
and a write queue with mitigation strategy for sidelining traffic.

---

## Architecture Overview

This system consists of:

- **Store Nodes** (primary & secondary): Persistent key-value stores with asynchronous primary copy replication
for fallback.
- **Queue**: Handles write requests with rate limiting and spillover strategies for excess and stale jobs.
- **API**: Front-facing service handling reads and forwarding writes to the queue.
- **Nginx**: Reverse proxy to route requests to the API.
- **Consistent Hashing**: Used to determine which store node is responsible for a given key.

```scss
           ┌───────────┐
           │   Client  │
           └─────┬─────┘
                 │
            ┌────▼────┐
            │  NGINX  │
            └────┬────┘
                 │
            ┌────▼────┐
            │   API   │
            └────┬────┘
         ┌───────┴────────┐
         │     Queue      │
         └───────┬────────┘ 
    ┌────────────▼────────────┐
    │     Store Primaries     │
    │    (store1 & store2)    │
    └───────────┬─────────────┘
      ┌─────────▼───────────┐
      │  Store Secondaries  │
      │ (replicated async)  │
      └─────────────────────┘

```

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