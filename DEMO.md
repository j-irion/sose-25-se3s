# SE3S Assignment Demo

by Julius Irion (456782) and Johannes Marold (393090)

## 0. Setup
We recommend opening two terminal windows or `tmux` panes for this demo. This enables us to view the logs while sending requests. We will label each command with `# T1` and `# T2` depending on which terminal it should be run in.

Firstly we shut down any existing containers and start the demo environment:
```sh
# T1
docker compose down
MAX_QUEUE_SIZE=100 WORKER_COUNT=1 SPILLOVER_QUEUE_SIZE=100 MAX_KEY_RATE=50 docker compose up --build --remove-orphans
```

## 1. Health Check
This confirms that the API is running and healthy. You should see how the application handles the request in `T1`. The response should be `HTTP/1.1 200 OK, {"status":"api up"}`.
```sh
# T2
curl -i http://localhost:8000/health
```

## 2. Basic Read/Write
Now we will increment counter `foo`. In stdout of `T1`, you should see the request being processed. The request is enqueued by the `api`, and then stored in `store2`. The response in `T2` should be `HTTP/1.1 202 Accepted, {"key":"foo","status":"queued"}`.
```sh
# T2
curl -i -X POST http://localhost:8000/counter/foo/increment 
```

Now the counter `foo` should be 1. We can read it back with a GET request. The response in `T2` should be `HTTP/1.1 200 OK, {"key":"foo","value":1}`.
```sh
# T2
curl -i http://localhost:8000/counter/foo
```

## 3. Back-pressure with spillover queue

### a) too many requests

This test sends 200 concurrent POST requests to increment the same key `bar`, simulating a high-load scenario. The system enforces several constraints:

- **Rate limiting per key** (`MAX_KEY_RATE=50`): Only 50 requests per key are accepted within a 10-second window. The rest are sidelined to the `EXCESS_QUEUE`, up to a capacity of 100.
- **Queue capacity** (`MAX_QUEUE_SIZE=100`): The main queue can hold only 100 jobs at once.
- **Worker throughput** (`WORKER_COUNT=1`): With only a single worker processing jobs, entries in the main queue can become stale if they are not processed within `STALE_THRESHOLD_SEC` (default 5 seconds).

In this test, the following occurs:
- 50 requests are immediately accepted into the main queue.
- The next 100 are rate-limited and placed into the `EXCESS_QUEUE`.
- The final 50 are rejected with `HTTP 429 Too Many Requests` because both queues are full.
- Additionally, due to the single worker processing slowly, some jobs in the main queue age beyond the stale threshold and are moved into the `STALE_QUEUE`, which you can observe using the logs.

```sh
# T2
seq 1 200 \
  | xargs -n1 -P50 -I{} curl -s -o /dev/null -w "%{http_code}\n" \
      -X POST http://localhost:8000/counter/bar/increment \
  | sort | uniq -c 
```
Expected output in terminal (exact values may vary depending on how fast the jobs are processed by the worker):
```sh
150 202 # successfully accepted
50 429 # rejected due to full queues
```

This should show a few log entries confirming staleness after 5 seconds:   
```sh
# T2
docker compose logs queue | grep "STALE_QUEUE" 
```
You can also check the logs for messages like: `[worker] sidelined key=bar to STALE_QUEUE (age 5.12s)`

### b) mixed rate test
This test demonstrates how the rate limiter works independently for different keys.

We send:
- **52 requests to `hotkey`**, exceeding the `MAX_KEY_RATE=50`, so 2 requests are expected to be redirected to the `EXCESS_QUEUE`.
- **5 requests to `chill`**, which is well within the rate limit, so all should be accepted without spillover.

This confirms that rate limiting is **per-key** and not global. The system handles hot and cold keys independently, which allows fair usage patterns across different clients or job types.

```sh
# T2
seq 1 52 \
  | xargs -n1 -P52 -I{} curl -s -o /dev/null -w "%{http_code}\n" \
      -X POST http://localhost:8000/counter/hotkey/increment \
  | sort | uniq -c 

seq 1 5 \
  | xargs -n1 -P5 -I{} curl -s -o /dev/null -w "%{http_code}\n" \
      -X POST http://localhost:8000/counter/chill/increment \
  | sort | uniq -c
```
You should see output like:

```sh
52 202 # hotkey accepted
5 202 # chill accepted
```
Use the logs to verify that only `hotkey` was rate-limited:
```sh
# T2
docker compose logs queue | grep "hotkey to EXCESS_QUEUE"
```
This should show 2 log entries confirming spillover.

No entries should appear for chill:
```sh
# T2
docker compose logs queue | grep "chill to EXCESS_QUEUE" 
```

## 4. Tune queue & no more 429s
By vertically scaling the queues and workers, we can handle more requests without hitting the `429 Too Many Requests` error. This allows us to process all 200 requests successfully.
```sh
# T1 (use ctrl + c to stop the running containers first)
docker compose down 
MAX_QUEUE_SIZE=1000 SPILLOVER_QUEUE_SIZE=500 MAX_KEY_RATE=50 WORKER_COUNT=4 docker compose up --build --remove-orphans
```
Now we can repeat the same test as before, but this time we should not see any `429` errors. Instead, all requests should be accepted with `202 Accepted`.
```sh
# T2
seq 1 200 \
  | xargs -n1 -P50 -I{} curl -s -o /dev/null -w "%{http_code}\n" \
      -X POST http://localhost:8000/counter/bar/increment \
  | sort | uniq -c 
```
Expected output:
```sh
200 202 # all requests accepted
```

## 5. Sharding Test

This test increments counter `A` and `B` ten times each in parallel. It demonstrates how the system routes requests to different storage shards based on the key using consistent hashing.

Since the increment logic is handled atomically inside each store node, we avoid race conditions, even with multiple concurrent workers.

```sh
# T2
for i in $(seq 1 10); do
  curl -s -X POST http://localhost:8000/counter/A/increment &
  curl -s -X POST http://localhost:8000/counter/B/increment &
done
wait
sleep 1

echo "A:"; curl http://localhost:8000/counter/A
echo "B:"; curl http://localhost:8000/counter/B
```
Expected output:
```sh
A: {"key":"A","value":"10"}
B: {"key":"B","value":"10"}
```
This confirms that all increments were processed correctly without loss or duplication.

To verify that each key was routed to its own shard, check the logs of the primary store nodes:
```sh
# T2
docker compose logs store1-primary \
  | grep "POST /store/B" | wc -l
docker compose logs store2-primary \
  | grep "POST /store/A" | wc -l
```
Expected output:
```sh
10 # for store1-primary (handling B)
10 # for store2-primary (handling A)
```

## 6. Replication Check

This test verifies that each secondary correctly reflects the state of its primary after a series of updates. The primary nodes push updates to their secondaries asynchronously. The secondaries reconcile their state by pulling updates from the primaries every 10 seconds. This approach ensures eventual consistency across the system.
```sh
# T2
echo "Primary1 B:";    curl http://localhost:9000/store/B
echo "Secondary1 B:"; curl http://localhost:9010/store/B
echo "Primary2 A:";    curl http://localhost:9001/store/A
echo "Secondary2 A:"; curl http://localhost:9011/store/A
```

## 7. Fail-over Demo

This test demonstrates that the system remains available for **reads** even when a primary store node is down. The API falls back to the corresponding **secondary**, ensuring high availability.

First, stop the primary store for shard1 (which handles key `B`):

```sh
# T2
docker compose stop store1-primary
```
Then, issue a read request for key B. The request should still succeed, as the API reads from the secondary:
```sh
# T2
curl -i http://localhost:8000/counter/B
```
Expected output (from the secondary):
```sh
HTTP/1.1 200 OK
{"key":"B","value":"10"}
```
This confirms that:
- The secondary is properly used as a failover read replica.
- The system is tolerant to primary failure for read operations.

You can optionally restart the primary after the test:
```sh
# T2
docker compose start store1-primary
```

## 8. Persistence Through Restart

This test verifies that the store nodes persist their data across restarts using the write-ahead log (`log.txt`).

Restart the primary store for shard2 (which handles key `A`):

```sh
# T2
docker compose restart store2-primary
```
Wait a few seconds to allow the store to replay its log and restore in-memory state. Then issue a read request:
```sh
# T2
curl http://localhost:8000/counter/A
```
This confirms that:
- All writes were durably logged before being acknowledged.
- On restart, the store replays its log and restores the previous state.
- The system provides persistence guarantees even without a full database.

## 9. Horizontal Scaling of API

This test demonstrates how the API layer can be **scaled horizontally** using Docker’s built-in routing mesh. Multiple API instances share the load, enabling higher throughput under concurrent traffic.

First, stop any existing containers and start the environment with **3 API replicas**:

```sh
# T1 (use ctrl + c to stop the running containers first)
docker compose down
MAX_QUEUE_SIZE=1000 SPILLOVER_QUEUE_SIZE=500 MAX_KEY_RATE=50 WORKER_COUNT=4 docker compose up --scale api=3
```
Confirm that 3 API containers are running:
```sh
# T2
docker compose ps api
```
Now send 300 concurrent increment requests to the API:
```sh
# T2
for i in $(seq 1 300); do
  curl -s -o /dev/null -w "%{http_code}\n" \
       -X POST http://localhost:8000/counter/foo/increment &
done | sort | uniq -c
```
Expected output (example):
```sh
  300 202
```
In the logs (`T1`), you should see requests being distributed across `api_1`, `api_2`, and `api_3`, confirming that the Docker routing mesh is balancing the load between all replicas.
This demonstrates that the API layer scales horizontally without additional configuration, allowing the system to handle higher request volumes efficiently.