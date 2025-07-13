import bisect
import hashlib


class ConsistentHash:
    """
    A simple implementation of consistent hashing with virtual nodes.

    This class distributes keys across a set of nodes such that:
    - Minimal keys are remapped when nodes are added or removed.
    - Virtual nodes (replicas) are used to improve key distribution.

    Attributes:
        replicas (int): Number of virtual nodes per physical node.
        ring (dict): Mapping of hash values to node identifiers.
        _sorted (list): Sorted list of hash values for bisecting.
    """
    def __init__(self, nodes, replicas=100):
        """
        Initialize the hash ring and add the initial nodes.

        Args:
            nodes (list): List of node identifiers (e.g., URLs or hostnames).
            replicas (int): Number of virtual nodes per real node.
        """
        self.replicas = replicas
        self.ring = {}
        self._sorted = []
        for node in nodes:
            self.add(node)

    def add(self, node):
        """
        Add a node to the hash ring with its virtual replicas.

        Args:
            node (str): Node identifier to add to the ring.
        """
        for i in range(self.replicas):
            h = self._hash(f"{node}-{i}")
            self.ring[h] = node
            self._sorted.append(h)
        self._sorted.sort()

    def get_node(self, key):
        """
        Get the node responsible for the given key.

        Args:
            key (str): The key to hash and route.

        Returns:
            str or None: The node identifier responsible for the key.
        """
        if not self.ring:
            return None
        h = self._hash(key)
        idx = bisect.bisect(self._sorted, h)
        if idx == len(self._sorted):
            idx = 0
        return self.ring[self._sorted[idx]]

    @staticmethod
    def _hash(x):
        """
        Compute a hash for the given input using MD5.

        Args:
            x (str): The input string to hash.

        Returns:
            int: A 128-bit integer hash.
        """
        return int(hashlib.md5(x.encode()).hexdigest(), 16)
