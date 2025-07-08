# SE3S Assignment Demo

by Julius Irion (456782) and Johannes Marold (XXXX)

## 0. Setup

```sh
docker compose down

MAX_QUEUE_SIZE=100 WORKER_COUNT=1 SPILLOVER_QUEUE_SIZE=100 docker compose up --build --remove-orphans
```

## 1. Health Check

```sh
curl -i http://localhost:8000/health
# → HTTP/1.1 200 OK, {"status":"api up"}
```

## 2. Basic Read/Write

```sh
# Increment key “foo”
curl -i -X POST http://localhost:8000/counter/foo/increment
```

```sh
# Read it back
curl -i http://localhost:8000/counter/foo
# → {"key":"foo","value":1}
```

## 3. Back-pressure with spillover queue

### a) too many requests

```sh
# 200 requests, 50 each concurrently
seq 1 200 \
  | xargs -n1 -P50 -I{} curl -s -o /dev/null -w "%{http_code}\n" \
      -X POST http://localhost:8000/counter/bar/increment \
  | sort | uniq -c

```

```sh
# view STALE_QUEUE
docker compose logs -f queue | grep "STALE_QUEUE"

```

### b) mixed rate test

```sh
# Send 52 increments to key=hotkey, and 5 to key=chill
# EXCESS THRESHOLD=50 should lead to 2 requests moved to EXCESS_QUEUE from hotkey
seq 1 52 \
  | xargs -n1 -P52 -I{} curl -s -o /dev/null -w "%{http_code}\n" \
      -X POST http://localhost:8000/counter/hotkey/increment \
  | sort | uniq -c

seq 1 10 \
  | xargs -n1 -P10 -I{} curl -s -o /dev/null -w "%{http_code}\n" \
      -X POST http://localhost:8000/counter/chill/increment \
  | sort | uniq -c
```

```sh
# Confirm spillover queue usage only for hotkey
docker compose logs queue | grep "hotkey to EXCESS_QUEUE"
```

```sh
# Confirm spillover queue usage not for chill
docker compose logs queue | grep "chill to EXCESS_QUEUE"
```

## 4. Tune queue & no more 429s

```sh
# Restart with larger queues and more workers
docker compose down
MAX_QUEUE_SIZE=1000 SPILLOVER_QUEUE_SIZE=500 WORKER_COUNT=4 docker compose up --build
```

```sh
# Repeat the same loop—now you should get all 202s:
seq 1 200 \
  | xargs -n1 -P50 -I{} curl -s -o /dev/null -w "%{http_code}\n" \
      -X POST http://localhost:8000/counter/bar/increment \
  | sort | uniq -c
```

## 5. Sharding Test

```sh
# Push 50 increments each to A and B in parallel
for i in $(seq 1 50); do
  curl -s -X POST http://localhost:8000/counter/A/increment &
  curl -s -X POST http://localhost:8000/counter/B/increment &
done
wait

# Read back both counters
echo "A:"; curl http://localhost:8000/counter/A
echo "B:"; curl http://localhost:8000/counter/B

```

## 6. Verify shards got their own traffic

```sh
# Count writes in each primary’s logs:
docker compose logs store1-primary \
  | grep "POST /store/B" | wc -l
docker compose logs store2-primary \
  | grep "POST /store/A" | wc -l
```

## 7. Replication check

```sh
# Read directly from each primary and secondary to confirm replication:
echo "Primary1 B:"; curl http://localhost:9000/store/B
echo "Secondary1 B:"; curl http://localhost:9010/store/B
echo "Primary2 A:"; curl http://localhost:9001/store/A
echo "Secondary2 A:"; curl http://localhost:9011/store/A
```

## 8. Fail-over demo

```sh
# Kill shard1 primary
docker compose stop store1-primary
```

```sh

# Reads for A should still work (served by secondary)
curl -i http://localhost:8000/counter/B
```

```sh
# (Optional) restart it
docker compose start store1-primary
```

## 9. Persistence through restart

```sh
# Restart shard2 primary
docker compose restart store2-primary

# After a few seconds for log-replay, A persists
curl http://localhost:8000/counter/A
```

## 10. Horizontal scaling of API

```sh
# Spin up 3 API replicas behind Docker’s routing mesh
docker compose up -d --scale api=3

```

```sh
# Confirm 3 instances
docker compose ps api
```

```sh
for i in $(seq 1 300); do
  curl -s -o /dev/null -w "%{http_code}\n" \
       -X POST http://localhost:8000/counter/foo/increment &
done | sort | uniq -c
```