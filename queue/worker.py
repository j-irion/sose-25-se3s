import time

def main():
    print("Worker started (not yet connected to anything)")
    while True:
        time.sleep(5)
        print("…still waiting for tasks")

if __name__ == "__main__":
    main()
