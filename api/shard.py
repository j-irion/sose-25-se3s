import hashlib, bisect

class ConsistentHash:
    def __init__(self, nodes, replicas=100):
        self.replicas = replicas
        self.ring = {}
        self._sorted = []
        for node in nodes:
            self.add(node)

    def add(self, node):
        for i in range(self.replicas):
            h = self._hash(f"{node}-{i}")
            self.ring[h] = node
            self._sorted.append(h)
        self._sorted.sort()

    def remove(self, node):
        for i in range(self.replicas):
            h = self._hash(f"{node}-{i}")
            del self.ring[h]
            self._sorted.remove(h)

    def get_node(self, key):
        if not self.ring:
            return None
        h = self._hash(key)
        idx = bisect.bisect(self._sorted, h)
        if idx == len(self._sorted):
            idx = 0
        return self.ring[self._sorted[idx]]

    @staticmethod
    def _hash(x):
        return int(hashlib.md5(x.encode()).hexdigest(), 16)
