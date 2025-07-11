# sose-25-se3s Prototyping Assignment

A sharded, replicated, and resilient **scalable counter system**.

This system supports:
- **Horizontal scaling** of the API layer.
- **Vertical scaling** via worker configuration.
- **Sharding** via consistent hashing for load isolation.
- **Asynchronous primary-copy replication** for high availability.
- **Eventual consistency** ensured by periodic reconciliation in the store replicas.
- **Write queueing** with spillover strategies for excess and stale traffic.

---

## Architecture Overview

This system is composed of the following services:

- **Store Nodes (Primary & Secondary)**  
  Each primary store handles writes and asynchronously replicates to its secondary.  
  Secondaries periodically reconcile with their primary to ensure **eventual consistency**, even if replication messages are missed or delayed.

- **Queue**  
  A thread-safe, rate-limited queue that handles write requests. Includes mitigation strategies:
  - `EXCESS_QUEUE` for key-based rate limiting,
  - `STALE_QUEUE` for age-based sidetracking of slow jobs.

- **API**  
  Stateless API layer that handles read requests directly and delegates writes to the queue.

- **Nginx**  
  Reverse proxy that load-balances requests across multiple API replicas using Docker’s routing mesh.

- **Consistent Hashing**  
  Maps each key to a store node shard, ensuring minimal disruption during scaling.



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

## Instructed Demo
For a step-by-step demonstration of the system’s capabilities, such as rate limiting, queueing, replication, failover, persistence, and scaling, see: [DEMO.md](./DEMO.md)