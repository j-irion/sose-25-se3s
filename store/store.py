class SimpleStore:
  def __init__(self, log_path="log.txt"):
    self.data = {}
    self.log_path = log_path

  def append(self, key, value):
    self.data[key] = value
    with open(self.log_path, "a") as f:
      f.write(f"{key}:{value}\n")

if __name__ == "__main__":
  s = SimpleStore()
  s.append("foo", "bar")
  print("Store data:", s.data)
