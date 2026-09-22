import io

try:
    t = io.open("logs/batch3c_console.txt", encoding="utf-8", errors="replace").read()
    print(len(t))
    print(t[-1200:])
except FileNotFoundError:
    print("NO FILE")
